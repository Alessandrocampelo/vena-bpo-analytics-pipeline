"""Landing local + upload para GCS, path determinístico por data.

Convenção de path (ADR-002): data/landing/<fonte>/dt=YYYY-MM-DD/... local,
replicado como landing/<fonte>/dt=YYYY-MM-DD/... no GCS. Reprocessar o
mesmo dia sobrescreve o mesmo prefixo em vez de acumular (ADR-007).
"""

import json
from collections.abc import Iterable
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from google.cloud import storage

from ingestion.config import Config

LANDING_ROOT = Path("data/landing")


def _landing_dir(fonte: str, run_date: date | None) -> Path:
    run_date = run_date or date.today()
    path = LANDING_ROOT / fonte / f"dt={run_date.isoformat()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json_landing(
    records: list[dict], fonte: str, run_date: date | None = None, filename: str = "data.ndjson"
) -> Path:
    """Grava records como newline-delimited JSON (um objeto por linha).

    NDJSON, não um array JSON único — é o formato que o load job do
    BigQuery espera para NEWLINE_DELIMITED_JSON (ver ADR-008).
    """
    target = _landing_dir(fonte, run_date) / filename
    lines = (json.dumps(record, ensure_ascii=False) for record in records)
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def write_parquet_landing(
    records: list[dict], fonte: str, run_date: date | None = None, filename: str = "data.parquet"
) -> Path:
    """Grava records (uma tabela pequena, cabe inteira em memória) como parquet."""
    target = _landing_dir(fonte, run_date) / filename
    pq.write_table(pa.Table.from_pylist(records), target)
    return target


def upload_to_gcs(config: Config, local_path: Path) -> str:
    """Sobe um arquivo de landing local para o bucket, replicando o path relativo
    (data/landing/... local -> gs://<bucket>/landing/... no GCS)."""
    relative = local_path.relative_to(LANDING_ROOT)
    blob_name = f"landing/{relative.as_posix()}"
    client = storage.Client(project=config.bq_project_id)
    bucket = client.bucket(config.gcs_bucket_name)
    bucket.blob(blob_name).upload_from_filename(str(local_path))
    return f"gs://{config.gcs_bucket_name}/{blob_name}"


def upload_all_to_gcs(config: Config, local_paths: Iterable[Path]) -> list[str]:
    return [upload_to_gcs(config, path) for path in local_paths]
