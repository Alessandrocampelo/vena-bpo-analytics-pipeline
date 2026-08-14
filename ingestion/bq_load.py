"""Carga da camada raw no BigQuery — partição diária + WRITE_TRUNCATE.

Decisão em docs/adr/ADR-008-carga-raw-bigquery.md: cada tabela raw é
particionada por tempo de ingestão, e cada carga sobrescreve só a
partição do dia (`tabela$YYYYMMDD`) — idempotente sem precisar de MERGE
nessa camada. Reutilizado por todos os assets Dagster que materializam
uma tabela raw, para não duplicar lógica de load job em cada um.
"""

import logging
from datetime import date
from enum import Enum

from google.cloud import bigquery

from ingestion.config import Config

logger = logging.getLogger(__name__)

# O dataset compartilhado já continha tabelas raw_*/stg_*/mart_*
# pré-existentes (de origem alheia a este trabalho, anteriores à Etapa 1 —
# ver ADR-008). Esse sufixo evita colidir com esses objetos sem apagá-los
# ou modificá-los; toda tabela criada por este pipeline passa por
# raw_table_name() em vez de montar o nome manualmente.
RAW_TABLE_SUFFIX = "_candidato_alessandro"


def raw_table_name(base_name: str) -> str:
    return f"{base_name}{RAW_TABLE_SUFFIX}"


class SourceFormat(str, Enum):
    PARQUET = "PARQUET"
    NDJSON = "NEWLINE_DELIMITED_JSON"


def load_to_raw_partition(
    config: Config,
    gcs_uris: str | list[str],
    table_name: str,
    run_date: date,
    source_format: SourceFormat,
) -> bigquery.LoadJob:
    """Carrega gcs_uris na partição de run_date de <dataset>.<table_name>.

    Cria a tabela (particionada por tempo de ingestão) automaticamente no
    primeiro load, com schema autodetectado a partir do próprio arquivo.
    """
    if isinstance(gcs_uris, str):
        gcs_uris = [gcs_uris]

    client = bigquery.Client(project=config.bq_project_id)
    destination = f"{config.bq_project_id}.{config.bq_dataset}.{table_name}${run_date:%Y%m%d}"

    job_config = bigquery.LoadJobConfig(
        source_format=source_format.value,
        autodetect=True,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        time_partitioning=bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.DAY),
    )

    job = client.load_table_from_uri(gcs_uris, destination, job_config=job_config)
    job.result()

    logger.info(
        "raw carregado: destino=%s linhas=%s bytes=%s",
        destination,
        job.output_rows,
        job.output_bytes,
    )
    return job
