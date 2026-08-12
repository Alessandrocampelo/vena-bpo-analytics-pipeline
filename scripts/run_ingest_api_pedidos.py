"""CLI: ingestão completa da API de vendas -> landing local + GCS.

Uso: python scripts/run_ingest_api_pedidos.py
"""

import logging
import time
from datetime import date

from ingestion.api_pedidos import CircuitBreakerError, VendasApiClient
from ingestion.config import load_config
from ingestion.storage import upload_to_gcs, write_json_landing

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_ingest_api_pedidos")


def main() -> None:
    config = load_config()
    client = VendasApiClient(config)
    run_date = date.today()

    t0 = time.monotonic()
    try:
        records = client.fetch_all(page_size=500)
    except CircuitBreakerError:
        logger.error("Ingestão abortada pelo circuit breaker — não seguiu com dado parcial.")
        raise
    elapsed = time.monotonic() - t0

    local_path = write_json_landing(records, "api_pedidos", run_date)
    gcs_uri = upload_to_gcs(config, local_path)

    stats = client.stats()
    logger.info(
        "linhas_processadas=%s tentativas=%s erros_retryable=%s taxa_erro=%.2f%% "
        "tempo_s=%.1f landing_local=%s landing_gcs=%s",
        len(records),
        stats["total_attempts"],
        stats["retryable_errors"],
        stats["error_rate"] * 100,
        elapsed,
        local_path,
        gcs_uri,
    )


if __name__ == "__main__":
    main()
