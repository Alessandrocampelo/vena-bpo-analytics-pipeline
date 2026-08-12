# Diagrama de Fluxo — Dia 1

Diagrama de referência da arquitetura decidida nas ADRs. Ele é a versão
"alto nível" — o grafo de assets do Dagster propriamente dito (com nomes
exatos de cada asset, schedule, sensor e retry policy) será detalhado no
Dia 3, quando a orquestração for implementada.

```mermaid
flowchart TB
    subgraph FONTES["Fontes de Dados"]
        API["API de Vendas\n(Cloud Run, REST paginado)"]
        SCRAP["Scraping de Concorrentes\n(HTML, schema drift por request)"]
        SQLITE["Banco Transacional\n(SQLite: clientes, produtos, itens_pedido)"]
    end

    subgraph INGESTAO["Ingestão — Dagster assets Python (ADR-006)"]
        ING_API["Pull paginado\nconcorrência limitada + backoff\n(ADR-006)"]
        ING_SCRAP["Parser em cadeia\nA / B / C / fallback\n(ADR-006)"]
        ING_SQLITE["Extração em chunks\nfetchmany 50k linhas\n(ADR-002)"]
    end

    subgraph LANDING["Landing — gs://vena-teste-candidato-ae (ADR-002)"]
        L_API["landing/api_pedidos/dt=.../*.json"]
        L_SCRAP["landing/scraping/dt=.../*.html"]
        L_SQLITE["landing/sqlite/*/dt=.../*.parquet"]
    end

    subgraph RAW["RAW — BigQuery: vena-teste.teste_tecnico_ae (ADR-002, ADR-007)"]
        R_API["raw_pedidos_api\n(load job, MERGE por pedido_id)"]
        R_SCRAP["raw_precos_concorrentes"]
        R_CLI["raw_clientes"]
        R_PRO["raw_produtos"]
        R_ITENS["raw_itens_pedido\n(MERGE por item_id)"]
    end

    subgraph STAGING["STAGING — dbt models (ADR-001, ADR-004, ADR-005)"]
        S_API["stg_pedidos_api\ntipagem defensiva"]
        S_SCRAP["stg_precos_concorrentes\nnormalização de preço/estoque"]
        S_CLI["stg_clientes\ndedup por CPF (ADR-004)"]
        S_PRO["stg_produtos\ntipagem preco/ativo"]
        S_ITENS["stg_itens_pedido\nflags fk_valido (ADR-005)"]
        DIM_CLI["dim_clientes_scd2\nhistórico por CPF"]
    end

    subgraph MART["MART — dbt models (ADR-003)"]
        F_API["fct_pedidos_api"]
        F_ITENS["fct_itens_pedido"]
        M_PRECO["mart_precos_competitividade"]
        M_SAUDE["mart_saude_comercial\n(tabela final para BI)"]
    end

    BI["Dashboard de Saúde Comercial\n(BI / ferramenta de visualização)"]

    API --> ING_API --> L_API --> R_API --> S_API --> F_API
    SCRAP --> ING_SCRAP --> L_SCRAP --> R_SCRAP --> S_SCRAP --> M_PRECO
    SQLITE --> ING_SQLITE --> L_SQLITE
    L_SQLITE --> R_CLI --> S_CLI --> DIM_CLI
    L_SQLITE --> R_PRO --> S_PRO
    L_SQLITE --> R_ITENS --> S_ITENS --> F_ITENS

    S_PRO --> M_PRECO
    S_PRO --> F_ITENS
    S_PRO --> F_API
    DIM_CLI --> F_ITENS
    DIM_CLI --> F_API

    F_API --> M_SAUDE
    F_ITENS --> M_SAUDE
    M_PRECO --> M_SAUDE
    M_SAUDE --> BI

    classDef orquestrado fill:#2b6cb0,color:#fff,stroke:#1a4971
    class ING_API,ING_SCRAP,ING_SQLITE orquestrado
```

## Notas de leitura do diagrama

- **Caixa azul (`ING_*`)**: assets Python orquestrados diretamente pelo
  Dagster, com `RetryPolicy` e schedule diário — é onde vive a resiliência
  de ingestão (ADR-006).
- **STAGING/MART**: modelos dbt, orquestrados pelo Dagster via
  `dagster-dbt` (ADR-001) — cada caixa é um asset dbt no grafo, não um
  script solto.
- **`F_API` e `F_ITENS` não se unem em uma tabela de fatos única** — são
  ramos paralelos até `mart_saude_comercial`, que os agrega lado a lado
  (ADR-003). Essa é a decisão de design mais visível do diagrama e a que
  mais precisa ser explicada na apresentação técnica.
- **`dim_clientes_scd2` alimenta os dois fatos** — é a dimensão
  compartilhada, deduplicada por CPF (ADR-004), com histórico tipo 2.
- Não há seta de `RAW` de volta para as fontes — landing no GCS é o único
  ponto de reprocessamento; a API/scraping não precisam ser consultados de
  novo para reconstruir `staging`/`mart`.

## O que falta neste diagrama (propositalmente, é o escopo do Dia 3)

- Nome exato de cada schedule/sensor do Dagster.
- Onde entra o `RetryPolicy` e o `run_failure_sensor` (asset de scraping).
- Os asset checks customizados (taxa de fallback do parser, taxa de FK
  inválida, prova de idempotência) — vão aparecer como nós de check
  anexados aos assets correspondentes, não como caixas de dados.
