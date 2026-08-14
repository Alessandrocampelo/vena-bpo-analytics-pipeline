# ADR-010 — Mart de saúde comercial: dimensões, fatos e prova de idempotência

**Status:** Aceita — Etapa 5

## Contexto

Faltava a última camada do requisito obrigatório "raw → staging → mart":
a tabela analítica final pronta para BI que alimenta o dashboard de saúde
comercial pedido no enunciado. Investigação real feita antes do desenho
(mesma disciplina das etapas anteriores):

- **`cliente_id`/`produto_id` da API de vendas cabem inteiramente no
  universo real de `clientes`/`produtos`** (`cliente_id` 1–6000 vs.
  `clientes` até 7137; `produto_id` 1–800 = exatamente `produtos`) —
  diferente de `itens_pedido`, cujos IDs excedem esse universo (ADR-003).
  Isso significa que a API **pode e deve** ser enriquecida com as
  dimensões de cliente/produto, ao contrário de `itens_pedido`. Taxa real
  de órfão: 245/48.000 (0,51%) de `cliente_id` sem correspondência, 0 de
  `produto_id`.
- **`stg_pedidos_api` também tem 245/48.000 (0,51%) linhas com
  `quantidade` nula** — sujeira da mesma natureza da já documentada em
  `itens_pedido` (ADR-005), não medida na Etapa 4 porque `stg_pedidos_api`
  não testava isso ainda. São linhas diferentes das 245 de cliente
  inválido (0 sobreposição confirmada por query) — duas sujeiras
  independentes.
- **Bug real encontrado nesta investigação, herdado da Etapa 4**:
  `stg_itens_pedido_candidato_alessandro.sql` fazia
  `safe_cast(data_item as date)`, mas `data_item` no raw é uma string
  datetime completa (`"2025-05-29 08:33:18"`). `SAFE_CAST(... AS DATE)`
  não aceita esse formato e retorna `NULL` silenciosamente — confirmado
  por query real que a coluna inteira (5.000.000 de linhas) estava nula.
  Corrigido para `SAFE_CAST(... AS DATETIME)`, que aceita o formato
  (validado com um valor real antes de aplicar). Corrigido neste commit,
  documentado com transparência — é uma correção sobre trabalho anterior,
  não um problema novo.
- **Segundo bug real, encontrado ao construir `mart_saude_comercial`**: o
  teste de `not_null` em `data` falhou com 1 linha — investigação mostrou
  que 235/48.000 linhas (0,49%) de `raw_pedidos_api` têm `data_pedido` no
  formato `"DD/MM/YYYY"` (ex.: `"01/10/2025"`) em vez do ISO 8601 do
  resto (`"2025-04-25T00:54:38"`). `SAFE_CAST(... AS TIMESTAMP)` retornava
  `NULL` silenciosamente para essas 235 linhas, que colapsavam num único
  grupo `data = NULL` no `GROUP BY` do mart. É exatamente a mesma classe
  de "formato inconsistente" que o enunciado já avisava (como
  `valor_unitario = "593.57 BRL"`, tratado na Etapa 2) — só que numa coluna
  diferente, não pega na amostragem da Etapa 1. Corrigido em
  `stg_pedidos_api_candidato_alessandro.sql` com
  `COALESCE(SAFE_CAST(data_pedido AS TIMESTAMP), SAFE.PARSE_TIMESTAMP('%d/%m/%Y', data_pedido))`
  — validado que as 235 linhas passam a parsear corretamente e o teste de
  grão do mart volta a passar.

## Decisão

### Dimensões

- **`dim_cliente_candidato_alessandro`**: fatia **atual** do snapshot SCD2
  (`scd_clientes_candidato_alessandro` onde `dbt_valid_to is null`), chave
  `cpf`. Decisão de apresentação adiada da ADR-004: `estado`/`segmento`
  nulos viram `'Não informado'` só aqui — a staging continua guardando
  `NULL` de verdade (mart é a única camada que decide apresentação para
  BI, staging nunca mascara ausência de dado).
- **`dim_produto_candidato_alessandro`**: de `stg_produtos`, `categoria`
  nula vira `'Não informado'` (achado real: 165/800 produtos sem
  categoria). Coluna adicional `status_ativo`
  (`'Ativo'/'Inativo'/'Não informado'`) para leitura direta em BI, mantendo
  o booleano `ativo` original também.

### Fatos

- **`int_clientes_bridge_candidato_alessandro`** (novo, `models/intermediate/`):
  promove para um modelo próprio a lógica de `cliente_id -> cpf` que até
  agora só existia como CTE inline dentro de `stg_itens_pedido` — agora
  tem um segundo consumidor (`fct_pedidos_api`), então duplicar deixou de
  ser razoável. Cobre todo o universo de `raw_clientes` (não só os
  sobreviventes do dedup por CPF), pelo mesmo motivo já registrado na
  ADR-009 (um `cliente_id` "perdedor" do dedup ainda é um cliente real).
- **`fct_pedidos_api_candidato_alessandro`**: `stg_pedidos_api` enriquecido
  via `int_clientes_bridge` (cliente_id → cpf → dim_cliente) e
  `dim_produto` (produto_id), sempre `LEFT JOIN` — mesmo princípio da
  ADR-005, agora estendido à API pelo achado de que a FK aqui é legítima.
  Flags `fk_cliente_valido`/`fk_produto_valido`/`quantidade_valida`
  espelhando o padrão já usado em `itens_pedido`. `receita =
  COALESCE(quantidade, 0) * valor_unitario`.
- **`fct_itens_pedido_candidato_alessandro`**: `stg_itens_pedido`
  enriquecido via `cliente_cpf` (já calculado na Etapa 4) → `dim_cliente`, e
  `produto_id` → `dim_produto`. Mesma fórmula de receita — aplica agora de
  fato a decisão que a ADR-005 previa para a camada mart (quantidade nula
  tratada como 0 só aqui, nunca na staging).

### Mart final

- **`mart_saude_comercial_candidato_alessandro`**: grão = dia. Une as duas
  fontes **lado a lado** por data (`FULL OUTER JOIN`), sem tentar
  unificar `pedido_id` entre elas — decisão já tomada na ADR-003 e mantida
  aqui. Colunas: `receita_api`, `pedidos_api_count`,
  `pct_fk_cliente_valida_api`, `pct_fk_produto_valida_api`,
  `receita_itens_pedido`, `itens_pedido_count`,
  `pct_fk_cliente_valida_itens`, `pct_fk_produto_valida_itens`.

### Testes / asset checks

- `unique`+`not_null` em `cpf` (dim_cliente), `produto_id` (dim_produto),
  `pedido_id` (fct_pedidos_api), `item_id` (fct_itens_pedido); teste
  singular de grão único por `data` em `mart_saude_comercial`. Como o mart
  entra no mesmo `@dbt_assets` da Etapa 4, esses testes aparecem
  automaticamente como Dagster asset checks (confirmado no log real do
  Etapa 4 — cada teste dbt virou um `ASSET_CHECK_EVALUATION`).

### Prova formal de idempotência (promessa da ADR-007)

Em vez de plumbing complexo de estado entre execuções do Dagster, a prova
é empírica e direta: materializar o job completo (raw+staging+mart) duas
vezes seguidas contra o mesmo dia, e comparar, para cada tabela mart,
`COUNT(*)` e um checksum agregado (`SUM(FARM_FINGERPRINT(TO_JSON_STRING(t)))`,
estável e independente de ordem de linha) entre a 1ª e a 2ª execução.
Resultado real documentado no README. Os testes de unicidade de chave
acima já são a salvaguarda permanente contra duplicação por
reprocessamento — a comparação dupla é a validação pontual que prova que
a promessa se sustenta na prática, sem inventar infraestrutura extra só
para isso.

### Observabilidade

Um asset check Python (mesmo padrão de `dagster_project/asset_checks.py`,
Etapa 3) em `mart_saude_comercial_candidato_alessandro`, reportando
metadata headline (linhas, soma de receita por fonte, intervalo de datas
coberto) — fecha "asset checks reportando métricas" também na camada
final, não só na raw.

## Achado real durante a prova de idempotência

A primeira tentativa da prova (rodar o job completo duas vezes e comparar
`COUNT`+checksum) revelou dois problemas reais, nessa ordem:

1. **`AssetCheckResult` com `decimal.Decimal`**: o asset check de
   observabilidade (`mart_saude_comercial_metadata_headline`) falhava com
   `DagsterInvalidMetadata` — `SUM(NUMERIC)` do BigQuery volta como
   `decimal.Decimal` em Python, e o Dagster não sabe serializar esse tipo
   em metadata sem conversão explícita. Corrigido com `float(...)` antes
   de colocar no dicionário de metadata.
2. **Checksum de `mart_saude_comercial` diferente entre as duas
   execuções, com `COUNT` idêntico**: investigação (dump linha a linha,
   `diff`) mostrou que `receita_itens_pedido` variava no último dígito
   (`15050225.34` vs. `15050225.340000002`) — soma de `FLOAT64` sobre
   milhões de linhas não é associativa, e a ordem de agregação num motor
   distribuído (BigQuery) pode variar entre execuções, produzindo
   representações de ponto flutuante ligeiramente diferentes para o
   "mesmo" valor. A causa raiz: `stg_itens_pedido` nunca convertia
   `valor_unitario` para `NUMERIC` (só `stg_pedidos_api` fazia isso desde
   a Etapa 4) — dinheiro estava sendo tratado como `FLOAT64` numa das duas
   fontes. Corrigido: `CAST(valor_unitario AS NUMERIC)` também em
   `stg_itens_pedido` (mesmo tratamento que a API já tinha).
   **Armadilha adicional encontrada ao aplicar a correção**: como
   `stg_itens_pedido` é um modelo **incremental**, um `dbt run` comum faz
   `MERGE` na tabela já existente (criada na Etapa 4 com a coluna em
   `FLOAT64`) — o tipo da coluna já materializada não muda só porque o
   `SELECT` mudou, e o valor `NUMERIC` novo era implicitamente reconvertido
   para `FLOAT64` na hora do merge, mascarando a correção silenciosamente.
   Só um `dbt run --full-refresh` (recriando a tabela do zero) aplicou o
   novo tipo de fato — documentado aqui porque é uma pegadinha genérica de
   qualquer mudança de tipo de coluna em modelo incremental, não específica
   deste bug.

Depois da correção completa (cast + full-refresh), as duas execuções do
mart produziram `COUNT` **e** checksum idênticos — resultado real no
README.

## Alternativas consideradas

- **Enriquecer `fct_pedidos_api` sem os flags de FK** (assumindo que a API
  é sempre limpa, já que os IDs cabem no universo real): descartada —
  medi e encontrei 0,51% de órfão real, mesma ordem de grandeza da sujeira
  de `itens_pedido`; ignorar isso repetiria o erro que a ADR-005
  explicitamente evita.
- **Provar idempotência via metadata de eventos do Dagster entre
  execuções** (guardando um checksum customizado na materialização e
  comparando com o penúltimo evento via `get_event_records`): considerada,
  mas descartada por complexidade desproporcional ao ganho — os testes de
  unicidade de chave já garantem a ausência de duplicação de forma
  permanente e automática; a comparação direta de `COUNT`+checksum entre
  duas execuções reais prova a mesma coisa de forma muito mais simples e
  auditável.
- **Manter `data_item` como `DATE`** (truncando a hora na correção do
  bug): descartada — `DATETIME` preserva a informação original por
  completo; o grão diário do mart é obtido com `DATE(data_item)` na hora
  de agregar, sem perder precisão na staging.

## Consequências

- Positivo: o mart reflete fielmente as decisões já tomadas nas camadas
  anteriores (CPF como identidade, FK sinalizada não descartada,
  itens_pedido/API como fatos distintos) sem reabri-las.
- Positivo: o bug de `data_item` foi pego antes de virar um número errado
  no dashboard final — a mesma disciplina de validar contra dado real que
  guiou as etapas anteriores.
- Negativo/risco assumido: `mart_saude_comercial` terá dias com uma fonte
  populada e a outra não (os ranges de data de `itens_pedido` e da API não
  se sobrepõem integralmente, achado já registrado na ADR-003) — isso é
  esperado e será comunicado na apresentação como característica do dado
  de teste, não como bug.
