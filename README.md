# Pipeline de Dados — Saúde Comercial (Vena BPO, teste técnico Analytics Engineer Sênior)

Pipeline ELT que consolida 3 fontes heterogêneas (API de vendas, scraping
de preços de concorrentes, banco transacional SQLite) em camadas
raw → staging → mart no BigQuery, orquestrado em Dagster, para alimentar
um dashboard diário de saúde comercial.

> **Status:** em desenvolvimento. Este README cresce a cada dia do
> desenvolvimento (ver cronograma abaixo). No momento cobre o **Dia 2**.

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
- [ ] Dia 3 — Ingestão: scraping resiliente + grafo Dagster (schedule,
  sensor, retry policy).
- [ ] Dia 4 — Staging: dedup, tipagem, SCD2, flags de qualidade + dbt
  tests.
- [ ] Dia 5 — Mart + asset checks + prova de idempotência +
  observabilidade.
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

## Estrutura do repositório

```
docs/
  01-descoberta.md        # achados reais nas 3 fontes (evidência)
  02-diagrama-fluxo.md     # diagrama Mermaid da arquitetura
  adr/                     # 7 ADRs, uma decisão por arquivo
ingestion/                 # API de vendas, extração SQLite, landing/storage
scripts/                   # CLIs de execução manual da ingestão
tests/                     # testes automatizados (mocks, sem rede/arquivo real)
pyproject.toml             # dependências (pip install -e ".[dev]")
.env.example               # variáveis de ambiente esperadas
```

Para rodar localmente: copie `.env.example` para `.env`, preencha os
caminhos/credenciais reais, `pip install -e ".[dev]"` e
`python scripts/run_ingest_api_pedidos.py` /
`python scripts/run_ingest_sqlite.py`.

(Pastas de transformação/orquestração — `dbt/`, `dagster_project/` —
chegam a partir do Dia 3.)

## Segurança

A chave da service account (`sa-candidato-ae.json`, fornecida pelo
avaliador) **não é versionada neste repositório**. É referenciada via
variável de ambiente `GOOGLE_APPLICATION_CREDENTIALS`, conforme
`.gitignore`.

## Uso de IA no desenvolvimento

Seção detalhada será adicionada ao final do desenvolvimento (Dia 6),
cobrindo ferramentas usadas, metodologia e o que não foi delegado à IA —
conforme pedido no enunciado.
