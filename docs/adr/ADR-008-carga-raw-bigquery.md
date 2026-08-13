# ADR-008 — Carga raw no BigQuery: partição diária + WRITE_TRUNCATE por partição

**Status:** Aceita — Dia 3

## Contexto

O Dia 2 entregou ingestão + landing (GCS) para API de vendas e SQLite,
mas nada ainda carrega os dados nas tabelas `raw` do BigQuery — essa
etapa fica naturalmente acoplada à orquestração Dagster (cada asset
`raw_*` materializa como uma tabela real no dataset
`vena-teste.teste_tecnico_ae`), então é decidida agora, no Dia 3.

Requisito de idempotência já fixado na ADR-007: "o pipeline deve poder
rodar duas vezes seguidas sem duplicar dados". Na camada raw, isso pode
ser resolvido de duas formas: `MERGE` por chave natural, ou substituição
completa de uma fatia bem definida dos dados (partição por dia).

## Decisão

- Toda tabela `raw` é **particionada por tempo de ingestão**
  (`bigquery.TimePartitioning(type_=DAY)`).
- Cada carga usa o **decorator de partição** no destino
  (`dataset.tabela$YYYYMMDD`, onde `YYYYMMDD` vem do `run_date` da
  execução, não da data real do load) com
  `write_disposition=WRITE_TRUNCATE`.
- Schema é autodetectado a partir do Parquet/NDJSON em GCS
  (`autodetect=True`) — a camada raw é fiel à fonte, sem tipagem manual
  (isso é trabalho da staging, Dia 4).

## Alternativas consideradas

- **`MERGE` por chave natural na raw** (mesmo mecanismo do
  ADR-004/ADR-007 para SCD2): descartada para esta camada — MERGE exige
  carregar primeiro numa tabela de staging temporária e depois `MERGE`,
  adicionando uma etapa extra e um custo de query só para reproduzir o
  que particionamento + truncamento por partição já resolve de forma mais
  simples e mais barata (load job substitui load job, sem query
  intermediária). Reservo `MERGE` para onde ele é indispensável: SCD2 de
  cliente na staging, que raw não tem.
- **Append sem partição + dedup na leitura**: descartada — repete o
  problema já rejeitado na ADR-007 (empurra custo de dedup pra toda
  leitura, e polui o histórico raw com execuções repetidas do mesmo dia).

## Atualização (Dia 3) — nomes de tabela com sufixo `_candidato_alessandro`

Ao validar a carga de `raw_produtos` contra o dataset real, o load falhou
(`BadRequest: Cannot add storage to a non-partitioned table...`) porque
**o dataset `vena-teste.teste_tecnico_ae` já continha um pipeline
completo pré-existente** — `raw_*`, `stg_*`, `dim_*`/`fct_*`,
`mart_saude_comercial_diaria` — com dados reais, criado em 31/07 e
01/08/2026, **antes do início deste trabalho** (Dia 1 começou em
11/08/2026). Não fui eu quem criou: nunca havia tocado o BigQuery neste
projeto antes deste passo (Dias 1-2 só usaram GCS).

Reportei o achado ao avaliador antes de prosseguir (pode ser uma
referência dele deixada por engano no dataset compartilhado, ou dado de
outro candidato usando o mesmo dataset/service account — em ambos os
casos, não era meu para apagar ou sobrescrever). Decisão combinada:
**toda tabela criada por este pipeline usa o sufixo `_candidato_alessandro`**
(ex.: `raw_produtos_candidato_alessandro`), evitando colisão com os
objetos pré-existentes sem tocar neles. Convenção centralizada em
`ingestion/bq_load.py::raw_table_name()` — nenhum outro módulo monta o
nome da tabela manualmente.

## Consequências

- Positivo: idempotência simples e barata — rodar o pipeline duas vezes
  no mesmo dia sobrescreve exatamente a mesma partição, sem custo de
  MERGE.
- Positivo: cada partição representa exatamente "o estado da fonte visto
  nesse dia" — útil para auditoria e para depurar schema drift do
  scraping (dá pra comparar partições dia a dia).
- Negativo: um reprocessamento *retroativo* (ex.: rodar hoje para
  reconstruir a partição de 3 dias atrás) precisa passar `run_date`
  explicitamente — o código já suporta isso (não usa "hoje" como
  premissa), mas é preciso lembrar de passar a data certa.
