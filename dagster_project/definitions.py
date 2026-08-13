"""Ponto de entrada do projeto Dagster (`dagster dev`, aponta pra cá via
`[tool.dagster] module_name` no pyproject.toml).
"""

from dagster import Definitions

from dagster_project.asset_checks import (
    raw_itens_pedido_linhas_esperadas,
    raw_pedidos_api_linhas_batem_com_reportado,
    raw_precos_concorrentes_taxa_fallback,
)
from dagster_project.assets import (
    raw_clientes,
    raw_itens_pedido,
    raw_pedidos_api,
    raw_precos_concorrentes,
    raw_produtos,
)
from dagster_project.dbt_assets import dbt_resource, staging_dbt_assets
from dagster_project.jobs import daily_raw_job, scraping_job
from dagster_project.schedules import daily_schedule
from dagster_project.sensors import scraping_failure_alert

defs = Definitions(
    assets=[
        raw_clientes,
        raw_produtos,
        raw_itens_pedido,
        raw_pedidos_api,
        raw_precos_concorrentes,
        staging_dbt_assets,
    ],
    asset_checks=[
        raw_itens_pedido_linhas_esperadas,
        raw_pedidos_api_linhas_batem_com_reportado,
        raw_precos_concorrentes_taxa_fallback,
    ],
    resources={"dbt": dbt_resource},
    jobs=[daily_raw_job, scraping_job],
    schedules=[daily_schedule],
    sensors=[scraping_failure_alert],
)
