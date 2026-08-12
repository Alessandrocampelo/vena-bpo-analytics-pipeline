"""Configuração central da ingestão, lida via variáveis de ambiente (.env)."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    api_base_url: str
    api_token: str
    sqlite_db_path: str
    gcs_bucket_name: str
    bq_project_id: str
    bq_dataset: str
    api_max_concurrency: int
    api_max_retries: int
    sqlite_chunk_size: int


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Variável de ambiente obrigatória não definida: {name}")
    return value


def load_config() -> Config:
    """Carrega e valida a configuração. Lança RuntimeError se algo obrigatório faltar."""
    return Config(
        api_base_url=_require("VENA_API_BASE_URL"),
        api_token=_require("VENA_API_TOKEN"),
        sqlite_db_path=_require("SQLITE_DB_PATH"),
        gcs_bucket_name=_require("GCS_BUCKET_NAME"),
        bq_project_id=_require("BQ_PROJECT_ID"),
        bq_dataset=_require("BQ_DATASET"),
        api_max_concurrency=int(os.environ.get("API_MAX_CONCURRENCY", "4")),
        api_max_retries=int(os.environ.get("API_MAX_RETRIES", "6")),
        sqlite_chunk_size=int(os.environ.get("SQLITE_CHUNK_SIZE", "50000")),
    )
