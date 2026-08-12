"""CLI: extração completa de clientes/produtos/itens_pedido -> landing local + GCS.

Uso: python scripts/run_ingest_sqlite.py
"""

import logging
import time
from datetime import date

from ingestion.config import load_config
from ingestion.sqlite_extract import (
    extract_clientes,
    extract_itens_pedido_chunks,
    extract_produtos,
)
from ingestion.storage import upload_all_to_gcs, upload_to_gcs, write_parquet_landing

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_ingest_sqlite")


def main() -> None:
    config = load_config()
    run_date = date.today()
    t0 = time.monotonic()

    clientes = extract_clientes(config)
    produtos = extract_produtos(config)
    p_clientes = write_parquet_landing(clientes, "sqlite/clientes", run_date, "clientes.parquet")
    p_produtos = write_parquet_landing(produtos, "sqlite/produtos", run_date, "produtos.parquet")
    upload_all_to_gcs(config, [p_clientes, p_produtos])
    logger.info("clientes: %s linhas | produtos: %s linhas", len(clientes), len(produtos))

    total_itens = 0
    n_chunks = 0
    for i, chunk in enumerate(extract_itens_pedido_chunks(config), start=1):
        n_chunks = i
        total_itens += len(chunk)
        path = write_parquet_landing(
            chunk, "sqlite/itens_pedido", run_date, filename=f"chunk_{i:05d}.parquet"
        )
        upload_to_gcs(config, path)
        if i % 20 == 0:
            logger.info("itens_pedido: %s chunks / %s linhas processadas até agora", i, total_itens)

    elapsed = time.monotonic() - t0
    logger.info(
        "itens_pedido_chunks=%s itens_pedido_linhas=%s tempo_total_s=%.1f",
        n_chunks,
        total_itens,
        elapsed,
    )


if __name__ == "__main__":
    main()
