# Pipeline de Dados — Saúde Comercial (Vena BPO, teste técnico Analytics Engineer Sênior)

Pipeline ELT que consolida 3 fontes heterogêneas (API de vendas, scraping
de preços de concorrentes, banco transacional SQLite) em camadas
raw → staging → mart no BigQuery, orquestrado em Dagster, para alimentar
um dashboard diário de saúde comercial.

> **Status:** em desenvolvimento. Este README cresce a cada dia do
> desenvolvimento (ver cronograma abaixo). No momento cobre o **Dia 5**.

## Cronograma de desenvolvimento

- [x] **Dia 1 — Descoberta + design.** Ver [`docs/01-descoberta.md`](docs/01-descoberta.md)
  (achados reais em cada fonte) e [`docs/adr/`](docs/adr/) (7 decisões de
  arquitetura, cada uma referenciando um achado concreto). Diagrama de
  fluxo em [`docs/02-diagrama-fluxo.md`](docs/02-diagrama-fluxo.md).
- [x] **Dia 2 — Ingestão: API de vendas + extração do SQLite em chunks.**
  Cliente da API ([`ingestion/api_pedidos.py`](ingestion/api_pedidos.py))
  com paginação, retry/backoff e cooldown compartilhado entre threads para
  o rate limit real do serviço (achado documentado na ADR-006). Extração
  do SQLite em chunks ([`ingestion/sqlite_extract.py`](ingestion/sqlite_extract.py))
  — `itens_pedido` (5M linhas) nunca é carregado de uma vez, validado com
  pico de ~54 MB de memória via `tracemalloc`. Landing local + GCS em
  [`ingestion/storage.py`](ingestion/storage.py). 11 testes automatizados
  em [`tests/`](tests/) (mocks, sem rede real). Scripts de execução manual
  em [`scripts/`](scripts/), validados de ponta a ponta contra a API, o
  `.sqlite` e o bucket reais: 48.000 pedidos e 5.000.000 de itens de
  pedido ingeridos com sucesso.
- [x] **Dia 3 — Ingestão: scraping resiliente + grafo Dagster (schedule,
  sensor, retry policy).** Parser em cadeia para os 3 layouts reais do
  scraping + fallback ([`ingestion/scraping_precos.py`](ingestion/scraping_precos.py)),
  testado com fixtures HTML reais e validado contra o serviço ao vivo (0
  linhas via fallback em 8 chamadas seguidas). Carga raw no BigQuery
  particionada por dia ([`ingestion/bq_load.py`](ingestion/bq_load.py),
  ADR-008). Projeto Dagster completo em
  [`dagster_project/`](dagster_project/): 5 assets raw, `RetryPolicy` no
  asset de scraping, schedule diário, sensor de falha e 3 asset checks —
  tudo validado de ponta a ponta contra API/scraping/SQLite/GCS/BigQuery
  reais (5.000.000 + 48.000 + 6.180 + 800 + 12 linhas materializadas), e
  o retry/alerta demonstrado provocando uma falha real com
  `FORCE_UNKNOWN_LAYOUT=true`.
- [x] **Dia 4 — Staging: dedup, tipagem, SCD2, flags de qualidade + dbt
  tests.** Projeto dbt em [`dbt/`](dbt/): `stg_clientes` (dedup por CPF,
  ADR-004), `stg_produtos` (tipagem defensiva de `ativo`/`preco_tabela`),
  `stg_itens_pedido` (incremental, flags `fk_cliente_valido`/
  `fk_produto_valido`/`quantidade_valida`, ADR-005), `stg_pedidos_api`
  (incremental, upsert por `updated_at`), `stg_precos_concorrentes`
  (histórico append-only, exceção deliberada — ADR-009). SCD2 do cliente
  via `dbt snapshot` (estratégia `check`), validado com uma mudança real
  simulada e revertida entre duas execuções, provando o histórico
  (`dbt_valid_from`/`dbt_valid_to`). 17 testes dbt (unicidade, not_null,
  `accepted_values`, taxa de FK reportada sem bloquear o build, ausência
  de sobreposição no SCD2). Integração `dagster-dbt`
  ([`dagster_project/dbt_assets.py`](dagster_project/dbt_assets.py)):
  staging entra no mesmo grafo Dagster como assets **dependentes de
  verdade** dos 5 assets raw — fecha o requisito de DAG com dependências
  reais que tinha ficado em aberto no Dia 3. Validado de ponta a ponta:
  materialização completa via Dagster (raw + staging + snapshot) contra
  API/scraping/SQLite/BigQuery reais, 23/23 nós dbt passando na mesma
  execução (5.995 clientes deduplicados, 800 produtos, 5.000.000 de itens
  de pedido com taxa de FK inválida batendo exatamente com o Dia 1).
- [x] **Dia 5 — Mart + asset checks + prova de idempotência +
  observabilidade.** Camada mart em [`dbt/models/marts/`](dbt/models/marts/):
  `dim_cliente` (fatia atual do SCD2), `dim_produto` (apresentação para
  BI), `fct_pedidos_api` e `fct_itens_pedido` (receita com `quantidade`
  nula tratada como 0, decisão da ADR-005 aplicada de fato), e
  `mart_saude_comercial` — grão diário, as duas fontes de pedido lado a
  lado sem forçar unificação (ADR-003). Achado novo: ao contrário de
  `itens_pedido`, os IDs de cliente/produto da API cabem no universo real
  — FK legítima, então `fct_pedidos_api` ganhou os mesmos flags de
  qualidade que `itens_pedido` já tinha. Dois bugs reais de formato de
  data encontrados e corrigidos nesta camada (`data_item` truncando tudo
  para `NULL`, 235 pedidos com `data_pedido` em `DD/MM/YYYY` em vez de
  ISO), documentados com transparência na
  [ADR-010](docs/adr/ADR-010-mart-saude-comercial.md). **Prova formal de
  idempotência**: pipeline completo materializado duas vezes seguidas
  contra o mesmo dia — `COUNT` e checksum (`BIT_XOR(FARM_FINGERPRINT(...))`)
  idênticos entre as duas execuções em todas as 5 tabelas mart, depois de
  corrigir um bug real de não-determinismo (soma de dinheiro em `FLOAT64`
  não é associativa em agregação distribuída — corrigido para `NUMERIC`
  em `stg_itens_pedido`, incluindo a pegadinha de que um modelo
  incremental precisa de `--full-refresh` para aplicar mudança de tipo de
  coluna). Observabilidade: novo asset check
  (`mart_saude_comercial_metadata_headline`) reportando linhas, receita
  por fonte e período coberto. Grafo completo (raw → staging → mart)
  validado de ponta a ponta via Dagster contra API/scraping/SQLite/BigQuery
  reais.
- [ ] Dia 6 — Documentação final, seção de uso de IA, revisão geral.
- [ ] Dia 7 — Buffer, ensaio da apresentação.

## Decisões de arquitetura (ADRs)

| ADR | Decisão |
|---|---|
| [ADR-001](docs/adr/ADR-001-stack-orquestracao-transformacao.md) | Dagster orquestra, dbt-bigquery transforma staging/mart |
| [ADR-002](docs/adr/ADR-002-camadas-e-landing.md) | Landing no GCS + carga em lote (não streaming) no BigQuery |
| [ADR-003](docs/adr/ADR-003-semantica-fontes-pedidos.md) | API de vendas e `itens_pedido` são fatos distintos, não a mesma tabela |
| [ADR-004](docs/adr/ADR-004-chave-identidade-cliente.md) | CPF (não `cliente_id`) é a chave de identidade/dedup do cliente |
| [ADR-005](docs/adr/ADR-005-integridade-referencial.md) | FK quebrada em `itens_pedido`: sinalizar, nunca descartar |
| [ADR-006](docs/adr/ADR-006-resiliencia-ingestao.md) | Concorrência limitada + backoff na API; parser em cadeia no scraping |
| [ADR-007](docs/adr/ADR-007-idempotencia.md) | Idempotência via `MERGE` por chave natural, não append cego |
| [ADR-008](docs/adr/ADR-008-carga-raw-bigquery.md) | Carga raw particionada por dia (`WRITE_TRUNCATE`); tabelas com sufixo `_candidato_alessandro` (ver nota abaixo) |
| [ADR-009](docs/adr/ADR-009-staging-dedup-scd2.md) | Staging: dedup por CPF, tipagem defensiva, SCD2 via `dbt snapshot`, incrementalidade por chave natural |
| [ADR-010](docs/adr/ADR-010-mart-saude-comercial.md) | Mart: dimensões/fatos, `mart_saude_comercial` por dia, prova formal de idempotência |

## Estrutura do repositório

```
docs/
  01-descoberta.md        # achados reais nas 3 fontes (evidência)
  02-diagrama-fluxo.md     # diagrama Mermaid da arquitetura
  adr/                     # 10 ADRs, uma decisão por arquivo
ingestion/                 # API de vendas, scraping, extração SQLite, landing/storage, carga BigQuery
dagster_project/           # assets raw, integração dbt, jobs, schedule, sensor, asset checks
dbt/                       # projeto dbt: staging, intermediate, marts (dim/fct/mart), snapshot SCD2, testes
scripts/                   # CLIs de execução manual da ingestão
tests/                     # testes automatizados (mocks/fixtures, sem rede/arquivo real)
pyproject.toml             # dependências (pip install -e ".[dev]")
.env.example               # variáveis de ambiente esperadas
```

Para rodar localmente: copie `.env.example` para `.env`, preencha os
caminhos/credenciais reais, `pip install -e ".[dev]"`, copie
`dbt/profiles.yml.example` para `dbt/profiles.yml`, e rode
`dagster dev` (UI do Dagster, materializa raw + staging com dependência
real entre eles) ou `python scripts/run_ingest_api_pedidos.py` /
`run_ingest_sqlite.py` (CLIs isolados). Para rodar só o dbt diretamente:
`cd dbt && DBT_PROFILES_DIR=. dbt build` (com as variáveis do `.env`
exportadas no shell — dbt não lê `.env` sozinho).

## Nota sobre o dataset BigQuery

Ao validar a primeira carga no Dia 3, encontrei um pipeline completo
(`raw_*`/`stg_*`/`dim_*`/`fct_*`/`mart_*`) já existente no dataset
compartilhado `vena-teste.teste_tecnico_ae`, criado em 31/07–01/08/2026 —
antes do início deste trabalho (Dia 1 começou em 11/08). Não fui eu quem
criou. Reportei o achado antes de prosseguir; a decisão combinada foi
usar o sufixo `_candidato_alessandro` em toda tabela criada por este
pipeline, para não colidir com os objetos pré-existentes sem apagá-los
ou modificá-los. Detalhes em
[ADR-008](docs/adr/ADR-008-carga-raw-bigquery.md).

## Segurança

A chave da service account (`sa-candidato-ae.json`, fornecida pelo
avaliador) **não é versionada neste repositório**. É referenciada via
variável de ambiente `GOOGLE_APPLICATION_CREDENTIALS`, conforme
`.gitignore`.

## Uso de IA no desenvolvimento

Seção detalhada será adicionada ao final do desenvolvimento (Dia 6),
cobrindo ferramentas usadas, metodologia e o que não foi delegado à IA —
conforme pedido no enunciado.
