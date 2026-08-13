# ADR-009 — Staging: dedup, tipagem, SCD2 e estratégia incremental

**Status:** Aceita — Dia 4

## Contexto

A camada `raw` (Dia 3) carrega, a cada execução, o **estado atual completo**
de cada fonte — a API de vendas sempre devolve as 48.000 linhas correntes,
e o SQLite é lido por inteiro a cada run. Cada carga fica isolada na
partição do dia (`WRITE_TRUNCATE` por `$YYYYMMDD`, ADR-008). Isso muda a
forma como a staging deve ler o raw: não é seguro fazer `UNION` de todas as
partições históricas (leria o mesmo dado se repetindo N vezes); cada modelo
de staging lê **só a partição mais recente** disponível de cada tabela raw.

Os requisitos obrigatórios do teste para esta camada são: deduplicação,
tipagem, e **SCD2 para o histórico de clientes** — e os achados do Dia 1
(ADR-004, ADR-005) já determinam boa parte do "como".

## Decisão

### Nomenclatura — mesmo sufixo `_candidato_alessandro` da raw (ADR-008)

O dataset compartilhado já continha, antes deste trabalho, objetos
`stg_*`/`dim_*`/`fct_*`/`mart_*` de origem alheia (achado do Dia 3,
ADR-008). A mesma colisão vale para staging: todo modelo dbt materializado
por este projeto usa o sufixo `_candidato_alessandro` **no próprio nome do
arquivo** (ex.: `stg_clientes_candidato_alessandro.sql`), já que por padrão
o nome da tabela materializada pelo dbt é o nome do arquivo do modelo — sem
precisar de `alias` customizado. Mesmo critério para o snapshot SCD2
(`scd_clientes_candidato_alessandro.sql`). Nenhum objeto pré-existente sem
esse sufixo é lido, alterado ou sobrescrito por este projeto dbt (exceto
via `source()`, que só lê a raw já criada por este mesmo pipeline).

### Leitura do raw — só a partição mais recente

Macro única `macros/ultima_particao.sql`, reaproveitada em todos os
modelos de staging que leem de uma fonte "estado atual" (clientes,
produtos, itens_pedido, pedidos_api):

```sql
{% macro ultima_particao(source_name, table_name) %}
  {% set relation = source(source_name, table_name) %}
  where date(_partitiontime) = (
    select max(date(_partitiontime)) from {{ relation }}
  )
{% endmacro %}
```

`stg_precos_concorrentes` é a exceção deliberada: não usa essa macro (ver
seção própria abaixo).

### `stg_clientes` — dedup por CPF (ADR-004)

- Chave de dedup: `cpf`, não `cliente_id` (achado do Dia 1: 185 CPFs
  duplicados vs. 12 `cliente_id` duplicados — CPF é a identidade real).
- Critério de desempate por CPF repetido: mantém a linha com **mais
  campos não nulos preenchidos** (maior completude); em empate, a de
  `data_cadastro` mais recente. Implementado com `ROW_NUMBER() OVER
  (PARTITION BY cpf ORDER BY completude DESC, data_cadastro DESC)`.
- Tipagem: `data_cadastro` (`TEXT` no raw) convertida para `DATE`.
  `estado`/`segmento`/`email` nulos permanecem `NULL` — não viram string
  `"desconhecido"` aqui; isso é decisão de apresentação do mart (Dia 5).
- Mojibake em `nome` (achado do Dia 1: `"Srta. Alexia Ara�jo"`) **não é
  corrigido** nesta staging — não há forma confiável de recuperar o
  caractere original sem acesso ao encoding de origem; documentado como
  limitação conhecida, não escondida.

### SCD2 do cliente — `dbt snapshot`, estratégia `check`

- `snapshots/scd_clientes.sql`, rodando sobre `stg_clientes` (pós-dedup),
  chave `cpf`.
- Estratégia **`check`**, não `timestamp`: `clientes` não tem nenhuma
  coluna de "última atualização" confiável — `data_cadastro` é a data do
  cadastro original, não de mudança. `check_cols` = todas as colunas de
  negócio (`nome, email, cidade, estado, segmento`).
- Cada `dbt snapshot` sucessivo compara o estado atual de `stg_clientes`
  contra a última versão snapshotada por CPF: se algo mudou, fecha a
  versão antiga (`dbt_valid_to`) e abre uma nova (`dbt_valid_from`) — é
  histórico real, não um `UPDATE` que apaga o estado anterior.

### `stg_produtos` — tipagem defensiva

- `ativo` (`TEXT`) tem duas convenções booleanas concorrentes nos dados
  reais: `'0'/'1'` e `'S'/'N'`, mais `NULL` (achado do Dia 1). Mapeado
  explicitamente: `'1'`/`'S'` → `true`, `'0'`/`'N'` → `false`, qualquer
  outro valor (incluindo `NULL`) → `NULL`. Não assume-se `CAST(ativo AS
  BOOL)` direto — quebraria em `'S'/'N'`.
- `preco_tabela` (`TEXT`, às vezes com prefixo `"R$ "`) parseado via
  `REGEXP_EXTRACT` para `NUMERIC` — mesma lógica defensiva já usada em
  `parse_valor_unitario` (`ingestion/api_pedidos.py`), reimplementada em
  SQL (não dá para reaproveitar código Python dentro de um modelo dbt).
- `produto_id` já é chave íntegra (800 valores distintos, achado do
  Dia 1) — sem dedup necessário, só tipagem.

### `stg_itens_pedido` — incremental + flags de FK (ADR-005)

- Modelo incremental, `unique_key='item_id'`,
  `incremental_strategy='merge'` — evita reprocessar as 5M linhas via
  full-refresh a cada run; a cada execução, faz merge da partição raw
  mais recente contra a tabela staging já materializada.
- `LEFT JOIN` (nunca `INNER`) com `stg_clientes` e `stg_produtos` —
  preserva a linha mesmo sem correspondência, conforme ADR-005.
- Flags: `fk_cliente_valido` (`cliente_id` encontrado em `stg_clientes`),
  `fk_produto_valido` (idem para `produto_id`), `quantidade_valida`
  (`quantidade IS NOT NULL`).
- `quantidade` **permanece `NULL`** na staging quando ausente — o
  `COALESCE(quantidade, 0)` para soma de receita é decisão do mart
  (Dia 5), não da staging, conforme já registrado na ADR-005.

### `stg_pedidos_api` — incremental + upsert por `updated_at` (ADR-007)

- Incremental, `unique_key='pedido_id'`, merge condicionado a manter a
  linha com `updated_at` mais recente — captura transição de status
  (`pago` → `cancelado`/`reembolsado`) de pedidos já carregados
  anteriormente, sem duplicar.
- Tipagem defensiva de `valor_unitario` reforçada também aqui (não confiar
  só na normalização já feita na ingestão, Dia 2) — staging não assume
  que o raw está sempre limpo.

### `stg_precos_concorrentes` — exceção: histórico append-only

- Diferente das demais fontes: uma cotação de concorrente é um fato
  pontual no tempo, não um "estado atual" a ser sobrescrito — preço varia
  legitimamente dia a dia, isso é o dado, não sujeira.
- Decisão: mantém **todas** as partições raw (sem aplicar
  `ultima_particao()`), com `data_coleta` = data da partição de origem.
  Sem dedup entre dias.
- `linha_via_fallback = (_parser_strategy = 'fallback')` como flag
  explícita de qualidade — insumo direto do asset check de taxa de
  fallback já existente no Dagster (Dia 3).

## Alternativas consideradas

- **Union de todas as partições raw para clientes/produtos/pedidos_api**:
  descartada — como cada partição já é o estado completo da fonte, isso
  processaria e potencialmente duplicaria o mesmo dado N vezes (N =
  número de dias rodados). Só faz sentido para `precos_concorrentes`,
  onde cada dia é, de fato, um fato novo.
- **`timestamp` strategy no snapshot de clientes usando `data_cadastro`**:
  descartada — `data_cadastro` é a data do cadastro original, não muda
  quando um campo é atualizado; usá-la como timestamp de mudança geraria
  histórico incorreto (nunca detectaria mudança em registro antigo).
- **Full-refresh em `stg_itens_pedido` a cada run** (em vez de
  incremental): descartada — reprocessaria 5M linhas todo dia sem
  necessidade; o requisito de idempotência (ADR-007) já aponta para
  incremental com merge por chave natural.

## Consequências

- Positivo: staging reflete fielmente as decisões já tomadas no Dia 1
  (CPF como identidade, FK sinalizada não descartada) sem reabrir essas
  discussões.
- Positivo: SCD2 é uma propriedade verificável (histórico real via
  `dbt snapshot`), não uma tabela que só guarda o estado mais recente.
- Positivo: `stg_itens_pedido` incremental evita custo de reprocessar 5M
  linhas via full-refresh a cada execução diária.
- Negativo/risco assumido: a estratégia "só a partição mais recente" para
  clientes/produtos/pedidos_api depende de o raw sempre representar o
  estado *completo* da fonte (verdade hoje, documentada como premissa) —
  se a fonte real algum dia passasse a ser genuinamente incremental, essa
  leitura precisaria mudar para uma janela de partições, não só a última.
- Teste de qualidade correspondente (Passo 8): unicidade de `cpf` em
  `stg_clientes`, unicidade de `item_id`/`pedido_id`/`produto_id` nas
  demais, taxa de FK inválida reportada (não falha o build), e ausência de
  sobreposição de janelas `dbt_valid_from`/`dbt_valid_to` no snapshot SCD2.
