{{
  config(
    materialized='table'
  )
}}

-- Fato de itens de pedido (SQLite, ADR-003: distinto de pedidos_api).
-- Flags de FK/quantidade já computadas na staging (ADR-005/ADR-009);
-- aqui só aplica a decisão de mart que a ADR-005 previa: quantidade nula
-- tratada como 0 apenas para soma de receita, nunca na staging.

select
    item_id,
    pedido_id,
    cliente_cpf,
    produto_id,
    data_item,
    quantidade,
    valor_unitario,
    coalesce(quantidade, 0) * valor_unitario as receita,
    fk_cliente_valido,
    fk_produto_valido,
    quantidade_valida
from {{ ref('stg_itens_pedido_candidato_alessandro') }}
