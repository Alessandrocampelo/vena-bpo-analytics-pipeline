# ADR-005 — FK quebrada em `itens_pedido`: sinalizar, nunca descartar

**Status:** Aceita — Etapa 1

## Contexto

O schema do SQLite não declara nenhuma `PRIMARY KEY`/`FOREIGN KEY` (
confirmado via `sqlite_master` — só existe um índice em
`itens_pedido(pedido_id)`). Isso significa que a integridade referencial
nunca foi garantida pelo banco; é 100% responsabilidade do pipeline decidir
o que fazer com órfãos.

Achados quantitativos (`docs/01-descoberta.md`, seção 3.3):

- 75.201 linhas (1,50%) de `itens_pedido` com `cliente_id` sem
  correspondência em `clientes`.
- 74.639 linhas (1,49%) com `produto_id` sem correspondência em
  `produtos`.
- 50.169 linhas (1,00%) com `quantidade` nula.
- `valor_unitario` nunca nulo e nunca ≤ 0 nas 5.000.000 de linhas — a
  sujeira está concentrada em `quantidade` e nas FKs, não no valor
  monetário.

`itens_pedido` é dado transacional == receita. Descartar 1,5% das linhas
silenciosamente distorce diretamente o número que vai para o dashboard de
"saúde comercial" da diretoria — é o pior lugar possível para perder dado
sem avisar.

## Decisão

- Toda linha de `itens_pedido` é **mantida** na staging
  (`stg_itens_pedido`), independentemente de FK quebrada ou `quantidade`
  nula.
- Adicionar colunas de flag explícitas: `fk_cliente_valido` (boolean),
  `fk_produto_valido` (boolean), `quantidade_valida` (boolean,
  `false` quando nula — nesse caso, a linha entra no mart com
  `quantidade` tratada como `0` **apenas** para fins de soma de receita
  agregada, mas a flag permanece visível para quem quiser excluir).
- Nenhum `INNER JOIN` entre `itens_pedido` e `clientes`/`produtos` na
  staging — sempre `LEFT JOIN`, preservando a linha mesmo sem
  correspondência.
- O mart expõe uma métrica própria de qualidade: `% de linhas com FK
  válida por dia de carga` — vira parte do asset check de observabilidade
  (Etapa 5), não só um número escondido em log.

## Alternativas consideradas

- **Descartar linhas com FK quebrada na staging** (`INNER JOIN` /
  `WHERE cliente_id IN (...)`- ): descartada — perde ~1,5% de receita
  real sem que a diretoria saiba, e o enunciado é explícito: "isso é
  proposital... parte do exercício é você decidir como tratar" (não
  "decidir se ignora").
- **Tentar "corrigir" o órfão inferindo um cliente/produto por
  aproximação** (ex.: matching por proximidade de ID): descartada — não
  há evidência que sustente esse tipo de inferência; seria inventar dado.

## Consequências

- Positivo: nenhuma perda silenciosa de receita; a taxa de FK quebrada
  fica visível e auditável, tanto no dbt test (como um teste que reporta
  a proporção, não um `not_null`/`relationships` que falharia o build
  inteiro) quanto no asset check do Dagster.
- Negativo: quem consumir o mart sem prestar atenção nas flags pode
  achatar `cliente`/`produto` como `"(desconhecido)"` sem perceber a
  causa — mitigado documentando isso no README e deixando as colunas de
  flag no mart final, não só na staging.
- Decisão consciente de **não** usar `relationships` do dbt como teste de
  build-fail para essas FKs — usaria um teste customizado que **reporta**
  a taxa, porque a "falha" aqui é esperada e conhecida, não um bug a ser
  bloqueado no CI.
