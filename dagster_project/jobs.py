"""Jobs de asset: um para a materialização diária completa, outro isolado
só para o asset de scraping (usado pelo sensor de falha e para a demo do
retry policy/alerta — ver ADR-006 e o plano do Dia 3)."""

from dagster import AssetSelection, define_asset_job

daily_raw_job = define_asset_job("daily_raw_job", selection=AssetSelection.all())

scraping_job = define_asset_job(
    "scraping_job", selection=AssetSelection.assets("raw_precos_concorrentes")
)
