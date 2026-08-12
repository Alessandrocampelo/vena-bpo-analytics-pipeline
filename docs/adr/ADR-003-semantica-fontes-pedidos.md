# ADR-003 — API de vendas e `itens_pedido` (SQLite) são tratados como fatos distintos

**Status:** Aceita — Dia 1

## Contexto

Existem duas fontes que parecem, à primeira vista, representar "pedidos":
a API de vendas (`pedido_id`, `cliente_id`, `produto_id`, `quantidade`,
`valor_unitario`, `status`) e a tabela `itens_pedido` do SQLite (mesmíssimos
nomes de coluna: `pedido_id`, `cliente_id`, `produto_id`, `quantidade`,
`valor_unitario`). A tentação natural é tratá-las como a mesma tabela de
fatos vinda de dois canais, e fazer `UNION` ou `JOIN` direto entre elas.

Os achados de descoberta (`docs/01-descoberta.md`, seções 1 e 3.3) mostram
que isso é uma armadilha:

- `itens_pedido.cliente_id` chega a **12.180**; a tabela `clientes` no
  mesmo banco só tem `cliente_id` até **7.137**.
- `itens_pedido.produto_id` chega a **1.300**; a tabela `produtos` só tem
  até **800**.
- O range de datas de `itens_pedido` (`2024-01-01` a `2025-07-29`) e o
  range observado nos pedidos da API (2025 avançando para 2026) não
  cobrem o mesmo período de forma consistente.
- `pedido_id` em ambas as fontes começa em 1 e cresce sequencialmente —
  ou seja, **não é um identificador global único entre as duas fontes**;
  `pedido_id=3` existe (com conteúdo diferente) tanto na API quanto no
  SQLite.

## Decisão

Tratar a API de vendas e `itens_pedido` como **dois fatos de negócio
independentes**, cada um com seu próprio grão e sua própria tabela mart
(`fct_pedidos_api` e `fct_itens_pedido`), sem tentar unificá-los por
`pedido_id`, `cliente_id` ou `produto_id`. Nenhum `JOIN`/`UNION` direto
entre as duas fontes usando essas chaves.

## Alternativas consideradas

- **Unificar como uma única tabela de pedidos** (`UNION ALL` por
  `pedido_id`): descartada — geraria colisão de grão (dois pedidos
  "id 3" completamente diferentes se sobrepondo) e , como o espaço de
  `cliente_id`/`produto_id` de `itens_pedido` excede o cadastro
  disponível, um `JOIN` para enriquecer com nome do cliente/produto
  produziria uma taxa artificialmente alta de "não encontrado" que não é
  um problema de qualidade de dado — é um problema de eu ter modelado a
  relação errada.
- **Assumir que é erro de dado e tentar mapear os IDs "extras" por algum
  outro critério (nome, data)**: descartada por falta de evidência — não
  há campo comum que sustente esse mapeamento; seria inventar uma regra
  de negócio não pedida.

## Consequências

- Positivo: cada mart reflete fielmente o grão e a semântica da fonte de
  onde veio — mais fácil de explicar e defender na apresentação técnica.
- Positivo: evita o efeito "métricas erradas por engenharia, não por
  sujeira de dado real" — que seria pior do que simplesmente reportar taxa
  de FK quebrada dentro de cada fonte isoladamente (ADR-005).
- Negativo: o "dashboard de saúde comercial" final (`mart_saude_comercial`)
  precisa agregar as duas fontes lado a lado (ex.: "receita via API" e
  "receita via itens_pedido") em vez de uma métrica única de "receita
  total" sem ambiguidade — isso é comunicado explicitamente no README e na
  apresentação como uma limitação conhecida do dado de teste, não
  escondido.
- Ainda assim, dentro de **cada fonte**, o enriquecimento com `clientes` e
  `produtos` é feito normalmente (LEFT JOIN), com a taxa de órfãos tratada
  pela ADR-005.
