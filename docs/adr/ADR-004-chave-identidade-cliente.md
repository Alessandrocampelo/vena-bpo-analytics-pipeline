# ADR-004 — CPF como chave de identidade e de deduplicação do cliente

**Status:** Aceita — Etapa 1

## Contexto

`clientes` tem 6.180 linhas, mas:

- `cliente_id` distinto: 6.168 (12 IDs duplicados)
- `cpf` distinto: 5.995 (**185 CPFs duplicados** — mais do que a
  duplicidade por ID)
- a combinação `nome + cpf` já é 100% distinta (6.180) — ou seja, não há
  linhas byte-a-byte idênticas para simplesmente `DISTINCT`.

Ou seja: existem pessoas reais cadastradas mais de uma vez, com
`cliente_id` diferentes (provavelmente por múltiplos cadastros ao longo do
tempo), e isso é *mais frequente* do que duplicidade acidental do próprio
`cliente_id`. Exemplo real: CPF `703.164.259-07` aparece em 3 linhas com
3 `cliente_id` diferentes.

## Decisão

- **CPF é a chave de negócio (identidade real) do cliente**, não
  `cliente_id`.
- Na staging (`stg_clientes`), dedup é feito por CPF, não por
  `cliente_id`. Critério de desempate quando há múltiplas linhas para o
  mesmo CPF: manter a linha com **mais campos não nulos preenchidos**
  (maior "completude"); em empate de completude, manter a de
  `data_cadastro` mais recente (assume-se que o cadastro mais novo tem
  informação mais atualizada).
- `cliente_id` é preservado como atributo técnico de rastreamento (para
  religar com `itens_pedido`, que só tem `cliente_id`), mas a dimensão de
  cliente na mart passa a ter uma chave surrogate própria por CPF
  deduplicado — todos os `cliente_id` associados ao mesmo CPF apontam
  para a mesma linha de dimensão.

## Alternativas consideradas

- **Dedup por `cliente_id`** (abordagem ingênua de `SELECT DISTINCT` ou
  `ROW_NUMBER() OVER (PARTITION BY cliente_id)`): descartada — resolveria
  só 12 casos e deixaria 185 CPFs (pessoas reais) representados como
  clientes diferentes na dimensão, inflando contagem de clientes únicos no
  dashboard de saúde comercial.
- **Dedup por `email`**: descartada como chave primária de dedup — 378
  linhas têm `email` nulo, então não cobre todos os casos; usado apenas
  como critério auxiliar de completude no desempate.

## Consequências

- Positivo: métrica de "quantidade de clientes únicos" no
  `mart_saude_comercial` reflete pessoas reais, não linhas de cadastro.
- Positivo: a lógica de SCD2 (histórico de clientes, requisito
  obrigatório do teste) passa a rastrear mudanças por CPF — coerente com
  "histórico da mesma pessoa", que é a intenção de negócio de um SCD2 de
  cliente.
- Negativo/risco assumido: CPF como string vem sem validação de dígito
  verificador nos dados de teste; não farei validação de CPF real (fora de
  escopo) — assume-se que o CPF, ainda que sintético, é estável como
  identificador.
- Teste de qualidade correspondente (Etapa 4/5): `dbt test` de unicidade de
  CPF em `stg_clientes` pós-dedup, e teste de que `cliente_id` → CPF é uma
  função (não ambíguo) antes do merge de SCD2.
