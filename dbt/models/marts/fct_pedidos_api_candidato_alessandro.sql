{{
  config(
    materialized='table'
  )
}}

-- Fato de vendas via API (ADR-003: distinto de itens_pedido, não unificar
-- por pedido_id/cliente_id/produto_id). Achado da Etapa 5 (ADR-010): ao
-- contrário de itens_pedido, cliente_id/produto_id da API cabem
-- inteiramente no universo real de clientes/produtos — FK legítima, por
-- isso ganha o mesmo tratamento de flags que itens_pedido (ADR-005),
-- LEFT JOIN sempre, nunca INNER. receita trata quantidade nula como 0
-- (decisão de mart, não de staging).

with fonte as (

    select *
    from {{ ref('stg_pedidos_api_candidato_alessandro') }}

),

clientes_bridge as (

    select cliente_id, cpf
    from {{ ref('int_clientes_bridge_candidato_alessandro') }}

),

produtos as (

    select produto_id
    from {{ ref('dim_produto_candidato_alessandro') }}

)

select
    f.pedido_id,
    cb.cpf as cliente_cpf,
    f.produto_id,
    f.data_pedido,
    f.updated_at,
    f.status,
    f.quantidade,
    f.valor_unitario,
    coalesce(f.quantidade, 0) * f.valor_unitario as receita,
    cb.cliente_id is not null as fk_cliente_valido,
    p.produto_id is not null as fk_produto_valido,
    f.quantidade is not null as quantidade_valida
from fonte f
left join clientes_bridge cb on f.cliente_id = cb.cliente_id
left join produtos p on f.produto_id = p.produto_id
