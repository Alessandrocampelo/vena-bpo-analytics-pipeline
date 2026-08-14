"""Parser resiliente do scraping de preços de concorrentes.

A estrutura do HTML muda a cada request (ADR-006) — reexplorado ao vivo
na Etapa 3: são 3 layouts conhecidos, capturados em
tests/fixtures/scraping_layout_{a,b,c}.html. O parser tenta cada
estratégia em cadeia; se nenhuma reconhecer, cai num fallback genérico
por regex; se nem o fallback extrair nada, retorna vazio — quem decide
se isso é falha dura é o chamador (o asset Dagster), não este módulo.

Detalhe de parsing não óbvio: no Layout C, produto e categoria vêm
concatenados como "Produto (Categoria)", e um produto real chama-se
"Meia Performance (3un)" — já tem parênteses no próprio nome. O regex de
split usa um grupo final não guloso pela direita (captura só o ÚLTIMO
"(...)" como categoria), assumindo que categoria nunca tem parênteses
(verdade nos dados observados: Calçados, Acessórios, etc.).
"""

import logging
import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from ingestion.config import Config

logger = logging.getLogger(__name__)

_PRECO_RE = re.compile(r"\d+(?:[.,]\d+)?")
_PRODUTO_CATEGORIA_RE = re.compile(r"^(.*)\s\(([^()]+)\)$")


class ScrapingParseError(Exception):
    """Nenhuma estratégia de parsing (nem o fallback) conseguiu extrair dados."""


@dataclass
class ScrapingResult:
    records: list[dict]
    strategy: str  # "A" / "B" / "C" / "fallback"


def _parse_preco(raw: str) -> float | None:
    match = _PRECO_RE.search(raw)
    if not match:
        return None
    return float(match.group(0).replace(",", "."))


def _split_produto_categoria(item: str) -> tuple[str, str | None]:
    match = _PRODUTO_CATEGORIA_RE.match(item)
    if not match:
        return item.strip(), None
    return match.group(1).strip(), match.group(2).strip()


def _parse_layout_a(soup: BeautifulSoup) -> list[dict] | None:
    """Tabela #tabela-precos, uma linha por (produto, concorrente)."""
    table = soup.find(id="tabela-precos")
    if table is None:
        return None
    rows = table.select("tr.produto-row")
    if not rows:
        return None
    return [
        {
            "produto_nome": row.find(class_="nome").get_text(strip=True),
            "categoria": row.find(class_="categoria").get_text(strip=True),
            "preco": _parse_preco(row.find(class_="preco").get_text(strip=True)),
            "concorrente": row.find(class_="concorrente").get_text(strip=True),
            "disponibilidade": row.find(class_="estoque").get_text(strip=True),
        }
        for row in rows
    ]


def _parse_layout_b(soup: BeautifulSoup) -> list[dict] | None:
    """Grid de divs #price-grid > .price-card[data-product][data-store]."""
    cards = soup.select("#price-grid .price-card")
    if not cards:
        return None
    return [
        {
            "produto_nome": card.get("data-product"),
            "categoria": card.find(class_="pc-cat").get_text(strip=True),
            "preco": _parse_preco(card.find(class_="pc-price").get_text(strip=True)),
            "concorrente": card.get("data-store"),
            "disponibilidade": card.find(class_="pc-stock").get_text(strip=True),
        }
        for card in cards
    ]


def _parse_layout_c(soup: BeautifulSoup) -> list[dict] | None:
    """Tabela .comparativo, com produto+categoria concatenados em col-item."""
    table = soup.find(class_="comparativo")
    if table is None:
        return None
    rows = table.select("tbody tr")
    if not rows:
        return None
    records = []
    for row in rows:
        produto_nome, categoria = _split_produto_categoria(
            row.find(class_="col-item").get_text(strip=True)
        )
        records.append(
            {
                "produto_nome": produto_nome,
                "categoria": categoria,
                "preco": _parse_preco(row.find(class_="col-valor").get_text(strip=True)),
                "concorrente": row.find(class_="col-loja").get_text(strip=True),
                "disponibilidade": row.find(class_="col-disp").get_text(strip=True),
            }
        )
    return records


def _parse_fallback(soup: BeautifulSoup) -> list[dict] | None:
    """Último recurso: acha qualquer texto em formato de preço e usa o texto dos
    elementos irmãos como contexto. Impreciso por natureza — só existe pra não
    derrubar o pipeline num layout nunca visto; não é esperado rodar em produção."""
    records = []
    for text_node in soup.find_all(string=_PRECO_RE):
        preco = _parse_preco(str(text_node))
        if preco is None:
            continue
        container = text_node.parent.parent if text_node.parent else None
        if container is None:
            continue
        campos = [c.get_text(strip=True) for c in container.find_all() if c.get_text(strip=True)]
        records.append(
            {
                "produto_nome": campos[0] if len(campos) > 0 else None,
                "categoria": campos[1] if len(campos) > 1 else None,
                "preco": preco,
                "concorrente": campos[2] if len(campos) > 2 else None,
                "disponibilidade": campos[3] if len(campos) > 3 else None,
            }
        )
    return records or None


_STRATEGIES = [("A", _parse_layout_a), ("B", _parse_layout_b), ("C", _parse_layout_c)]


def parse_html(html: str, force_unknown_layout: bool = False) -> tuple[list[dict], str]:
    """Tenta cada estratégia em ordem. Retorna (records, nome_da_estrategia).

    force_unknown_layout simula um layout nunca visto (nenhuma estratégia
    nem o fallback são tentados) — usado só para demonstrar deliberadamente
    o retry policy / alerta do Dagster (ver ADR-006), nunca em produção.
    """
    if force_unknown_layout:
        logger.error("force_unknown_layout=True — simulando falha total de parsing")
        return [], "nenhuma"

    soup = BeautifulSoup(html, "html.parser")

    for name, strategy in _STRATEGIES:
        try:
            records = strategy(soup)
        except Exception:
            logger.warning("Estratégia %s levantou exceção ao parsear — tentando próxima", name)
            records = None
        if records:
            return records, name

    records = _parse_fallback(soup)
    if records:
        logger.warning(
            "Nenhum dos 3 layouts conhecidos reconhecido — usando fallback genérico (%d linhas)",
            len(records),
        )
        return records, "fallback"

    logger.error("Nenhuma estratégia (incluindo fallback) conseguiu extrair dados do HTML")
    return [], "nenhuma"


@retry(
    retry=retry_if_exception_type(requests.exceptions.RequestException),
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
    reraise=True,
)
def _fetch_html(config: Config) -> str:
    response = requests.get(f"{config.scraping_base_url}/concorrentes/precos", timeout=30)
    response.raise_for_status()
    return response.text


def fetch_precos_concorrentes(
    config: Config, force_unknown_layout: bool = False
) -> ScrapingResult:
    """Busca a página de preços e faz o parsing.

    Levanta ScrapingParseError se nenhuma estratégia (nem o fallback)
    conseguir extrair nada — cabe ao chamador (asset Dagster) decidir
    entre falhar/retry ou tolerar um dia com dado "stale" (ADR-006).
    """
    html = _fetch_html(config)
    records, strategy = parse_html(html, force_unknown_layout=force_unknown_layout)
    for record in records:
        record["_parser_strategy"] = strategy
    if strategy == "nenhuma":
        raise ScrapingParseError("Nenhuma estratégia de parsing reconheceu a página de preços.")
    return ScrapingResult(records=records, strategy=strategy)
