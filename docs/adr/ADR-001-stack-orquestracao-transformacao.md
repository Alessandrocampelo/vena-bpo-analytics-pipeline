# ADR-001 — Stack de orquestração e transformação: Dagster + dbt-bigquery

**Status:** Aceita — Etapa 1

## Contexto

O pipeline precisa orquestrar ingestão de 3 fontes heterogêneas (API, HTML,
SQLite) e depois transformar em camadas (raw → staging → mart) dentro do
BigQuery, com testes de qualidade, retry policy e observabilidade — tudo
isso são requisitos obrigatórios do teste (`Teste_Tecnico_...md`, seção
"Requisitos Técnicos Obrigatórios").

Duas abordagens possíveis:

1. **Tudo em Dagster**: ingestão em ops/assets Python, e as transformações
   SQL também escritas como assets Python que disparam queries no
   BigQuery diretamente.
2. **Dagster para orquestração + dbt para as camadas SQL** (staging/mart),
   usando o integration `dagster-dbt` para que os modelos dbt apareçam
   como assets no mesmo grafo de dependências.

## Decisão

Opção 2: **Dagster orquestra ingestão (assets Python) e agenda/observa;
dbt-bigquery é responsável pelas transformações SQL de staging e mart,
incluindo os testes de qualidade (`dbt test`)**.

## Alternativas consideradas

- **Tudo em Dagster (SQL solto em ops Python)**: descartada. Escrever
  dedup, tipagem e SCD2 como strings SQL soltas dentro de funções Python
  funciona, mas perde justamente o que dbt já resolve de forma madura:
  testes declarativos (`unique`, `not_null`, `relationships`), lineage
  automático de colunas, e SQL versionado/revisável como artefato de
  primeira classe. Para um teste que pesa 20% em "modelagem em camadas" e
  15% em "testes de qualidade", reinventar isso é risco desnecessário.
- **Só dbt, sem Dagster** (usando `dbt Cloud` ou cron simples): descartada
  porque o enunciado exige explicitamente orquestração em Dagster com
  "dependências reais entre assets... retry policy... asset checks" — não
  é negociável, é 20% da nota.

## Consequências

- Positivo: divisão de responsabilidade clara — Python/Dagster lida com
  I/O externo instável (API, scraping, SQLite), SQL/dbt lida com lógica de
  dados dentro do warehouse, onde é mais legível e testável.
- Positivo: `dagster-dbt` expõe cada modelo dbt como um asset individual no
  grafo — a dependência "real" entre staging e mart pedida no enunciado
  vem de graça da estrutura de `ref()` do próprio dbt.
- Negativo: duas ferramentas para configurar em vez de uma — mais
  boilerplate inicial (perfil dbt, `dbt_project.yml`, integração de
  credenciais da service account em ambos). Aceitável dado o ganho em
  testabilidade.
- Consequência prática: os asset checks customizados no Dagster (Etapa 5)
  vão focar no que dbt **não** expressa bem (taxa de fallback do parser
  de scraping, prova de idempotência via dupla execução) — não duplicar
  o que já é `dbt test`.
