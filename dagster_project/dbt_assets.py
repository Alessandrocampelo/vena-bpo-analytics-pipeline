"""Integração dbt <-> Dagster (Dia 4): a camada staging (dbt/models,
snapshots, tests) entra no mesmo grafo Dagster como assets dependentes dos
5 assets raw já existentes (dagster_project/assets.py) — fecha a exigência
"DAG com dependências reais entre assets" que ficou deliberadamente em
aberto no Dia 3, quando os 5 assets raw eram paralelos entre si.

A ligação raw -> staging é feita mapeando cada source dbt
(dbt/models/staging/_sources.yml, sempre "<base>_candidato_alessandro")
de volta para a AssetKey do asset raw correspondente ("<base>"), via
_RawSourceTranslator abaixo — sem isso, o dbt criaria um asset "stub"
solto para cada source em vez de reconhecer o asset raw já materializado.
"""

import os
from pathlib import Path
from typing import Any

from dagster import AssetExecutionContext, AssetKey
from dagster_dbt import DagsterDbtTranslator, DbtCliResource, DbtProject, dbt_assets
from dotenv import load_dotenv

load_dotenv()

DBT_PROJECT_DIR = Path(__file__).parent.parent / "dbt"

# Mesmo sufixo de dbt/models/staging/_sources.yml e ingestion/bq_load.py
# (RAW_TABLE_SUFFIX) — repetido aqui em vez de importado porque este
# módulo não deve depender de ingestion.bq_load só por causa de uma
# constante de nomenclatura.
_RAW_TABLE_SUFFIX = "_candidato_alessandro"

dbt_project = DbtProject(
    project_dir=DBT_PROJECT_DIR,
    profiles_dir=DBT_PROJECT_DIR,
)
dbt_project.prepare_if_dev()

dbt_resource = DbtCliResource(project_dir=dbt_project)


class _RawSourceTranslator(DagsterDbtTranslator):
    def get_asset_key(self, dbt_resource_props: dict[str, Any]) -> AssetKey:
        if dbt_resource_props["resource_type"] == "source":
            table_name = dbt_resource_props["name"]
            if table_name.endswith(_RAW_TABLE_SUFFIX):
                base_name = table_name[: -len(_RAW_TABLE_SUFFIX)]
                return AssetKey(base_name)
        return super().get_asset_key(dbt_resource_props)


@dbt_assets(
    manifest=dbt_project.manifest_path,
    project=dbt_project,
    dagster_dbt_translator=_RawSourceTranslator(),
)
def staging_dbt_assets(context: AssetExecutionContext, dbt: DbtCliResource):
    yield from dbt.cli(["build"], context=context).stream()
