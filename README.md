# Pipeline de Dados — Saúde Comercial (Vena BPO, teste técnico Analytics Engineer Sênior)

Pipeline ELT que consolida 3 fontes heterogêneas (API de vendas, scraping
de preços de concorrentes, banco transacional SQLite) em camadas
raw → staging → mart no BigQuery, orquestrado em Dagster, para alimentar
um dashboard diário de saúde comercial.

> **Status:** em desenvolvimento. Este README cresce a cada etapa do
> desenvolvimento (ver etapas abaixo). No momento cobre a **Etapa 6**.

## Etapas do desenvolvimento

- [x] **Etapa 1 — Descoberta + design.** Ver [`docs/01-descoberta.md`](docs/01-descoberta.md)
  (achados reais em cada fonte) e [`docs/adr/`](docs/adr/) (7 decisões de
  arquitetura, cada uma referenciando um achado concreto). Diagrama de
  fluxo em [`docs/02-diagrama-fluxo.md`](docs/02-diagrama-fluxo.md).
- [x] **Etapa 2 — Ingestão: API de vendas + extração do SQLite em chunks.**
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
- [x] **Etapa 3 — Ingestão: scraping resiliente + grafo Dagster (schedule,
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
- [x] **Etapa 4 — Staging: dedup, tipagem, SCD2, flags de qualidade + dbt
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
  reais que tinha ficado em aberto na Etapa 3. Validado de ponta a ponta:
  materialização completa via Dagster (raw + staging + snapshot) contra
  API/scraping/SQLite/BigQuery reais, 23/23 nós dbt passando na mesma
  execução (5.995 clientes deduplicados, 800 produtos, 5.000.000 de itens
  de pedido com taxa de FK inválida batendo exatamente com a Etapa 1).
- [x] **Etapa 5 — Mart + asset checks + prova de idempotência +
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
- [x] **Etapa 6 — Documentação final, seção de uso de IA, revisão geral.**
  Diagrama de fluxo ([`docs/02-diagrama-fluxo.md`](docs/02-diagrama-fluxo.md))
  atualizado para refletir a entrega real (SCD2 dividido em
  `scd_clientes`+`dim_cliente`, `int_clientes_bridge` incluído,
  `mart_precos_competitividade` do plano original marcado explicitamente
  como não implementado, com o porquê). Seção "Uso de IA no
  desenvolvimento" (abaixo) reescrita cobrindo ferramenta, metodologia,
  como o código foi revisado (4 casos reais de erro pego por validação
  contra dado real) e o que ficou como decisão humana. Revisão geral das
  10 ADRs e do README contra o estado real do repositório; suíte
  completa (21 testes pytest + 27 testes dbt) reconfirmada verde antes
  do commit.
- [ ] Etapa 7 — Buffer, ensaio da apresentação.

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

Ao validar a primeira carga na Etapa 3, encontrei um pipeline completo
(`raw_*`/`stg_*`/`dim_*`/`fct_*`/`mart_*`) já existente no dataset
compartilhado `vena-teste.teste_tecnico_ae`, criado em 31/07–01/08/2026 —
antes do início deste trabalho (Etapa 1 começou em 11/08). Não fui eu quem
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

### Ferramenta

[Claude Code](https://claude.com/claude-code) (Anthropic), modelo Sonnet
5, usado em todas as etapas — descoberta, design, implementação, testes,
documentação — como par de desenvolvimento dentro do meu editor, com
acesso direto ao terminal, ao BigQuery, à API e ao scraping reais (não um
chat à parte colando código).

### Metodologia

**Spec-first, uma etapa por vez, sem pular nenhuma.** Cada etapa de
desenvolvimento (a lista acima é literal, não retroativa) começou
com um plano escrito e explícito — decisões de arquitetura formalizadas
em ADR *antes* de qualquer linha de código, não depois para justificar o
que já tinha sido feito. Nenhum plano virou código sem eu aprovar
primeiro; dentro de cada plano, cada passo foi executado e validado
individualmente, e eu aprovava um por um antes do próximo — nunca "gera
tudo de uma vez e eu reviso no final". Isso deixou o volume de
trabalho por revisão pequeno o bastante para eu realmente entender cada
decisão, não só aceitar um diff grande.

**TDD-assistido onde fazia sentido, não como formalidade.** Os testes do
parser de scraping (`tests/test_scraping_precos.py`) usam fixtures HTML
capturadas ao vivo do serviço real, não inventadas — o caso do produto
"Meia Performance (3un)" com parênteses no próprio nome só apareceu
porque testei contra dado real antes de escrever o parser, não depois.
Os testes de circuito/retry da API (`tests/test_api_pedidos.py`) usam
`responses.add_callback` (não respostas estáticas empilhadas) porque uma
tentativa inicial com respostas estáticas escondia bugs de ordem em
concorrência — outro caso onde rodar contra o comportamento real (async,
condição de corrida) revelou uma limitação do que eu tinha pedido de
teste.

### Como o código gerado foi revisado

Nunca por leitura visual isolada. Toda decisão de peso foi validada
contra dado ou serviço **real** — BigQuery, API de vendas, scraping,
SQLite — com números conferidos por query direta, nunca assumidos porque
"parece certo". Quatro casos concretos, reais, deste repositório, onde
essa validação pegou um erro genuíno gerado pela IA (todos documentados
na ADR correspondente, com a correção visível no histórico, não
escondida):

1. **Retry-After capado errado** (ADR-006): uma primeira correção
   assumiu, com base num teste anterior mais curto, que o header
   `Retry-After` da API era pouco confiável e o capou em 10s — isso
   causou uma falha real (`CircuitBreakerError`) na validação de ponta a
   ponta seguinte. Só foi pego porque cada mudança era testada contra o
   serviço real antes de seguir, não por revisão de código.
2. **`SAFE_CAST(data_item AS DATE)` zerando 5.000.000 de linhas em
   silêncio** (ADR-010): o formato real de `data_item`
   (`"2025-05-29 08:33:18"`) não é aceito por `CAST ... AS DATE`, e o
   `SAFE_CAST` engole o erro devolvendo `NULL` para a coluna inteira sem
   nenhum aviso — só apareceu numa query de conferência (`MIN`/`MAX` da
   coluna vindo `NULL`), não por inspeção do SQL gerado.
3. **235 pedidos com `data_pedido` em `"DD/MM/YYYY"`** em vez de ISO
   8601 (ADR-010): passou despercebido na amostragem da Etapa 1 (~4.000
   registros) e só apareceu quando um teste de "grão único por data" no
   mart falhou com 1 linha de `data = NULL` — investiguei a fundo em vez
   de simplesmente relaxar o teste.
4. **Soma de dinheiro em `FLOAT64` não-determinística** (ADR-010): a
   prova de idempotência (rodar o pipeline duas vezes e comparar
   `COUNT`+checksum) mostrou `COUNT` idêntico mas checksum diferente —
   investigação por `diff` linha a linha achou que a soma de milhões de
   linhas em ponto flutuante não é associativa; a causa raiz era
   `valor_unitario` como `FLOAT64` em vez de `NUMERIC`. Corrigir isso
   revelou uma segunda pegadinha (modelo incremental não muda o tipo de
   coluna já materializada sem `--full-refresh`) — só descoberta porque
   comparei os dois runs de verdade, não porque assumi que "cast
   resolve".

Em nenhum desses quatro casos o erro foi visível olhando o código — só
apareceu testando contra comportamento real e comparando números. Isso
não é um acaso: foi o critério que usei o tempo todo para decidir quando
uma etapa estava "pronta" — nunca "compilou"/"rodou sem erro", sempre
"os números batem com o que eu esperava, e eu conferi por quê".

### O que não foi delegado à IA

As decisões de arquitetura e de negócio em si — não a redação delas —
foram minhas, tomadas em cima de evidência que eu pedi para levantar, não
escolhas automáticas aceitas de bandeja:

- CPF (não `cliente_id`) como identidade real do cliente (ADR-004);
  tratar API de vendas e `itens_pedido` como fatos distintos em vez de
  unificar por `pedido_id` (ADR-003); sinalizar FK quebrada em vez de
  descartar (ADR-005) — todas nasceram de eu pedir a exploração dos dados
  primeiro, e decidir depois de ver o achado quantitativo, não de uma
  sugestão genérica de "boas práticas".
- **A reação ao achado de um pipeline pré-existente e alheio no dataset
  compartilhado** (Etapa 3, ADR-008) foi explicitamente escalada para mim
  antes de qualquer ação — a IA parou, reportou o achado e perguntou como
  proceder, em vez de decidir sozinha nomear as tabelas de um jeito ou
  apagar/sobrescrever algo.
- A aprovação de cada plano (via revisão explícita antes de qualquer
  código) e de cada passo de execução dentro do plano foi manual, um por
  um, da Etapa 2 à Etapa 5 — nenhuma etapa rodou "no piloto automático".
- Revisão final de todo o código e da documentação antes de cada commit
  é minha — inclusive esta seção.
