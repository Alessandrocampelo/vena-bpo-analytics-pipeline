"""Asset checks de observabilidade/qualidade — rodam logo após a
materialização, consultando o BigQuery de verdade (não só reaproveitando
o que o asset disse que processou, exceto quando o próprio cruzamento
entre os dois é o ponto do check).
"""

from datetime import date

from dagster import AssetCheckResult, AssetCheckSeverity, AssetKey, asset_check
from google.cloud import bigquery

from dagster_project.assets import raw_itens_pedido, raw_pedidos_api, raw_precos_concorrentes
from ingestion.bq_load import raw_table_name
from ingestion.config import load_config

# Fixo no enunciado do teste (README_CANDIDATO.md): "itens_pedido (5.000.000 linhas)".
ITENS_PEDIDO_LINHAS_ESPERADAS = 5_000_000


def _count_rows_hoje(table_base_name: str) -> int:
    config = load_config()
    table = raw_table_name(table_base_name)
    client = bigquery.Client(project=config.bq_project_id)
    query = (
        f"SELECT COUNT(*) AS total FROM `{config.bq_project_id}.{config.bq_dataset}.{table}` "
        f"WHERE DATE(_PARTITIONTIME) = '{date.today().isoformat()}'"
    )
    return next(iter(client.query(query).result())).total


def _metadata_da_ultima_materializacao(context, asset_key: AssetKey) -> dict:
    event = context.instance.get_latest_materialization_event(asset_key)
    if event is None or event.asset_materialization is None:
        return {}
    return {k: v.value for k, v in event.asset_materialization.metadata.items()}


@asset_check(asset=raw_itens_pedido)
def raw_itens_pedido_linhas_esperadas(context) -> AssetCheckResult:
    """itens_pedido tem exatamente 5.000.000 de linhas — fixo no enunciado do teste."""
    count = _count_rows_hoje("raw_itens_pedido")
    passed = count == ITENS_PEDIDO_LINHAS_ESPERADAS
    return AssetCheckResult(
        passed=passed,
        metadata={"linhas_no_bigquery": count, "esperado": ITENS_PEDIDO_LINHAS_ESPERADAS},
    )


@asset_check(asset=raw_pedidos_api)
def raw_pedidos_api_linhas_batem_com_reportado(context) -> AssetCheckResult:
    """Confere que o que chegou no BigQuery bate com o que o cliente da API
    reportou ter processado (metadata da própria materialização) — pega
    perda silenciosa entre a extração e a carga."""
    count = _count_rows_hoje("raw_pedidos_api")
    metadata = _metadata_da_ultima_materializacao(context, raw_pedidos_api.key)
    reportado = metadata.get("linhas_processadas")
    passed = reportado is not None and count == reportado
    return AssetCheckResult(
        passed=passed,
        metadata={
            "linhas_no_bigquery": count,
            "linhas_reportadas_pelo_asset": reportado,
            "taxa_erro_da_ingestao": metadata.get("taxa_erro"),
        },
    )


@asset_check(asset=raw_precos_concorrentes)
def raw_precos_concorrentes_taxa_fallback(context) -> AssetCheckResult:
    """WARN (não falha o pipeline) se alguma linha veio do parser fallback —
    sinal de schema drift não coberto pelos 3 layouts conhecidos (ADR-006)."""
    metadata = _metadata_da_ultima_materializacao(context, raw_precos_concorrentes.key)
    linhas_fallback = metadata.get("linhas_via_fallback", 0)
    passed = linhas_fallback == 0
    return AssetCheckResult(
        passed=passed,
        severity=AssetCheckSeverity.WARN,
        metadata={"linhas_via_fallback": linhas_fallback, "estrategia": metadata.get("estrategia_parser")},
    )
