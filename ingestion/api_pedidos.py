"""Cliente da API de vendas: paginação, retry/backoff e limitador de taxa.

Decisões aplicadas aqui vêm de docs/adr/ADR-006-resiliencia-ingestao.md.

Achado empírico (Etapa 2): o rate limit da API não é por conexões
simultâneas — é burst (~20 requisições) + cooldown, aplicado pelo
servidor independentemente de quantas threads o cliente usa (medido com
concorrência 4 e 8: mesmo tempo total). Por isso o retry não usa backoff
exponencial independente por página — cada thread "adivinhando" seu
próprio tempo de espera briga com a mesma janela do servidor e
desperdiça tentativas. Em vez disso, um cooldown é compartilhado entre
todas as threads: a primeira a receber 429 marca "bloqueado até X", e
todas as outras (inclusive novas tentativas) esperam até esse instante
antes da próxima requisição.

Achado empírico #2 (e correção sobre ele): a API manda `Retry-After` no
429 contando um valor que cai exatamente com o relógio (59, 49, 39...) —
ou seja, é uma contagem regressiva precisa até o reset real da cota, não
um valor arbitrário. Uma primeira tentativa de "cortar" esse valor para
10s (achando, com base num teste anterior mais curto, que o header era
enganoso) causou falhas reais (CircuitBreakerError) porque o cliente
tentava de novo antes da cota voltar. Corrigido: o header é respeitado
integralmente. A cota parece ser algo como "~20-25 requisições por janela
de ~60s", e isso independe de concorrência/pacing do cliente — é uma
característica do serviço, não uma ineficiência do cliente. Por isso o
pull completo de 96 páginas fica em torno de 180s mesmo com a estratégia
correta: é o mínimo prático respeitando a cota real do servidor.
"""

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests
from tenacity import (
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ingestion.config import Config

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_CONSECUTIVE_FAILURES = 3
# Usado só quando o 429 não vem com Retry-After (defensivo — não
# observado em testes, mas o header pode não estar sempre presente).
DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS = 10.0


class PageFetchError(Exception):
    """Falha ao buscar uma página após esgotar as tentativas de retry."""


class CircuitBreakerError(Exception):
    """Abortado: falhas se acumularam além do limite tolerado."""


class _RetryableHTTPError(Exception):
    def __init__(self, status_code: int, retry_after: float | None = None):
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(f"HTTP {status_code}")


class _SharedCooldown:
    """Cooldown compartilhado entre threads: uma única janela de bloqueio,
    não uma por thread. Ver nota no topo do módulo."""

    def __init__(self, cooldown_seconds: float):
        self._cooldown_seconds = cooldown_seconds
        self._blocked_until = 0.0
        self._lock = threading.Lock()

    def wait_if_blocked(self) -> None:
        with self._lock:
            remaining = self._blocked_until - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)

    def trigger(self, seconds: float | None = None) -> None:
        with self._lock:
            self._blocked_until = time.monotonic() + (seconds or self._cooldown_seconds)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, requests.exceptions.ConnectionError | requests.exceptions.Timeout):
        return True
    return isinstance(exc, _RetryableHTTPError)


def _wait_for_retry(retry_state):
    exc = retry_state.outcome.exception()
    if isinstance(exc, _RetryableHTTPError) and exc.status_code == 429:
        # o cooldown compartilhado já garante a espera de verdade na
        # próxima chamada de _request_page; aqui só evita tentar de novo
        # no mesmo instante.
        return 0.5
    return wait_exponential_jitter(initial=1, max=10)(retry_state)


def parse_valor_unitario(raw: Any) -> float | None:
    """Parsing defensivo: aceita número puro ou string tipo '593.57 BRL'."""
    if raw is None:
        return None
    if isinstance(raw, int | float):
        return float(raw)
    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", str(raw))
    if not match:
        return None
    return float(match.group(0).replace(",", "."))


class VendasApiClient:
    """Cliente para GET /api/pedidos, com retry/backoff e paginação concorrente."""

    def __init__(self, config: Config, session: requests.Session | None = None):
        self._config = config
        self._session = session or requests.Session()
        self._cooldown = _SharedCooldown(DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS)
        self._retrying = Retrying(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(config.api_max_retries),
            wait=_wait_for_retry,
            reraise=True,
        )
        self._stats_lock = threading.Lock()
        self._total_attempts = 0
        self._retryable_errors = 0

    def stats(self) -> dict:
        """Métricas de observabilidade da última chamada a fetch_all/fetch_page."""
        with self._stats_lock:
            total, errors = self._total_attempts, self._retryable_errors
        return {
            "total_attempts": total,
            "retryable_errors": errors,
            "error_rate": (errors / total) if total else 0.0,
        }

    def _request_page(self, page: int, page_size: int) -> dict:
        self._cooldown.wait_if_blocked()
        with self._stats_lock:
            self._total_attempts += 1
        url = f"{self._config.api_base_url}/api/pedidos"
        response = self._session.get(
            url,
            params={"page": page, "page_size": page_size},
            headers={"Authorization": f"Bearer {self._config.api_token}"},
            timeout=30,
        )
        if response.status_code in RETRYABLE_STATUS_CODES:
            with self._stats_lock:
                self._retryable_errors += 1
            retry_after = response.headers.get("Retry-After")
            requested = float(retry_after) if retry_after else None
            if response.status_code == 429:
                logger.warning("429 recebido — Retry-After=%ss", requested)
                self._cooldown.trigger(requested)
            raise _RetryableHTTPError(response.status_code, requested)
        response.raise_for_status()
        return response.json()

    def fetch_page(self, page: int, page_size: int = 500) -> tuple[list[dict], dict]:
        """Busca uma página, com retry/backoff. Levanta PageFetchError se esgotar tentativas."""
        try:
            payload = self._retrying(self._request_page, page, page_size)
        except Exception as exc:
            raise PageFetchError(f"Página {page} falhou após todas as tentativas: {exc}") from exc

        records = payload.get("data", [])
        for record in records:
            record["valor_unitario"] = parse_valor_unitario(record.get("valor_unitario"))
            record["_source_page"] = page
        return records, payload

    def fetch_all(self, page_size: int = 500) -> list[dict]:
        """Puxa todas as páginas (concorrência limitada) e retorna a lista completa de pedidos."""
        first_records, first_payload = self.fetch_page(1, page_size)
        total_pages = first_payload["total_pages"]
        logger.info(
            "API de vendas: total_pages=%s total_records=%s",
            total_pages,
            first_payload.get("total_records"),
        )

        all_records: list[dict] = list(first_records)
        pages_remaining = range(2, total_pages + 1)

        # Falhas consecutivas contadas na ordem em que os resultados chegam
        # (não na ordem numérica das páginas, já que rodam em paralelo) —
        # é um sinal de degradação sustentada, não de uma página específica.
        consecutive_failures = 0
        with ThreadPoolExecutor(max_workers=self._config.api_max_concurrency) as executor:
            futures = {
                executor.submit(self.fetch_page, page, page_size): page
                for page in pages_remaining
            }
            for future in as_completed(futures):
                page = futures[future]
                try:
                    records, _ = future.result()
                    all_records.extend(records)
                    consecutive_failures = 0
                except PageFetchError:
                    consecutive_failures += 1
                    logger.error(
                        "Falha ao buscar página %s (falhas consecutivas: %s)",
                        page,
                        consecutive_failures,
                    )
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        for pending in futures:
                            pending.cancel()
                        raise CircuitBreakerError(
                            f"{consecutive_failures} páginas seguidas falharam — "
                            "abortando ingestão da API de vendas."
                        )
        return all_records
