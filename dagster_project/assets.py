"""Os 5 assets raw — cada um chama os módulos já existentes em `ingestion/`;
Dagster só orquestra, não reimplementa lógica de ingestão (ver ADR-001).

Sem dependência real *entre* esses 5 assets — todos são leitura de fonte,
independentes uns dos outros. A dependência real raw -> staging -> mart
aparece na Etapa 4, quando os modelos dbt referenciarem esses assets via
dagster-dbt (decisão registrada na ADR-001 e no plano da Etapa 3).
"""

from datetime import date

from dagster import AssetExecutionContext, RetryPolicy, asset

from ingestion.api_pedidos import VendasApiClient
from ingestion.bq_load import SourceFormat, load_to_raw_partition, raw_table_name
from ingestion.config import load_config
from ingestion.scraping_precos import fetch_precos_concorrentes
from ingestion.sqlite_extract import (
    extract_clientes,
    extract_itens_pedido_chunks,
    extract_produtos,
)
from ingestion.storage import upload_to_gcs, write_json_landing, write_parquet_landing


@asset
def raw_clientes(context: AssetExecutionContext) -> None:
    config = load_config()
    run_date = date.today()

    records = extract_clientes(config)
    local_path = write_parquet_landing(records, "sqlite/clientes", run_date, "clientes.parquet")
    gcs_uri = upload_to_gcs(config, local_path)
    table = raw_table_name("raw_clientes")
    load_to_raw_partition(config, gcs_uri, table, run_date, SourceFormat.PARQUET)

    context.add_output_metadata(
        {"linhas_processadas": len(records), "tabela_bigquery": table, "gcs_uri": gcs_uri}
    )


@asset
def raw_produtos(context: AssetExecutionContext) -> None:
    config = load_config()
    run_date = date.today()

    records = extract_produtos(config)
    local_path = write_parquet_landing(records, "sqlite/produtos", run_date, "produtos.parquet")
    gcs_uri = upload_to_gcs(config, local_path)
    table = raw_table_name("raw_produtos")
    load_to_raw_partition(config, gcs_uri, table, run_date, SourceFormat.PARQUET)

    context.add_output_metadata(
        {"linhas_processadas": len(records), "tabela_bigquery": table, "gcs_uri": gcs_uri}
    )


@asset
def raw_itens_pedido(context: AssetExecutionContext) -> None:
    config = load_config()
    run_date = date.today()

    total = 0
    gcs_uris = []
    for i, chunk in enumerate(extract_itens_pedido_chunks(config), start=1):
        total += len(chunk)
        local_path = write_parquet_landing(
            chunk, "sqlite/itens_pedido", run_date, filename=f"chunk_{i:05d}.parquet"
        )
        gcs_uris.append(upload_to_gcs(config, local_path))

    table = raw_table_name("raw_itens_pedido")
    load_to_raw_partition(config, gcs_uris, table, run_date, SourceFormat.PARQUET)

    context.add_output_metadata(
        {"linhas_processadas": total, "numero_chunks": len(gcs_uris), "tabela_bigquery": table}
    )


@asset
def raw_pedidos_api(context: AssetExecutionContext) -> None:
    config = load_config()
    run_date = date.today()
    client = VendasApiClient(config)

    records = client.fetch_all(page_size=500)
    local_path = write_json_landing(records, "api_pedidos", run_date)
    gcs_uri = upload_to_gcs(config, local_path)
    table = raw_table_name("raw_pedidos_api")
    load_to_raw_partition(config, gcs_uri, table, run_date, SourceFormat.NDJSON)

    stats = client.stats()
    context.add_output_metadata(
        {
            "linhas_processadas": len(records),
            "tentativas": stats["total_attempts"],
            "erros_retryable": stats["retryable_errors"],
            "taxa_erro": stats["error_rate"],
            "tabela_bigquery": table,
        }
    )


@asset(retry_policy=RetryPolicy(max_retries=3, delay=30))
def raw_precos_concorrentes(context: AssetExecutionContext) -> None:
    config = load_config()
    run_date = date.today()

    # levanta ScrapingParseError se nem o fallback conseguir extrair nada —
    # propositalmente não capturado aqui: é o que aciona o RetryPolicy (Passo 7)
    result = fetch_precos_concorrentes(config, force_unknown_layout=config.force_unknown_layout)

    local_path = write_parquet_landing(result.records, "scraping_precos", run_date, "precos.parquet")
    gcs_uri = upload_to_gcs(config, local_path)
    table = raw_table_name("raw_precos_concorrentes")
    load_to_raw_partition(config, gcs_uri, table, run_date, SourceFormat.PARQUET)

    linhas_fallback = sum(1 for r in result.records if r["_parser_strategy"] == "fallback")
    context.add_output_metadata(
        {
            "linhas_processadas": len(result.records),
            "estrategia_parser": result.strategy,
            "linhas_via_fallback": linhas_fallback,
            "tabela_bigquery": table,
        }
    )
