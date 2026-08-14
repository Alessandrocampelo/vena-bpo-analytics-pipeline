{{
  config(
    materialized='table'
  )
}}

-- Tabela final "pronta para BI" pedida no enunciado. Grão = dia. As duas
-- fontes de pedido (API e itens_pedido) ficam lado a lado por data, sem
-- tentar unificá-las por pedido_id/cliente_id/produto_id (ADR-003) — são
-- dois fatos de negócio independentes, cada um com sua própria taxa de
-- qualidade, e misturar as duas num "receita_total" único esconderia essa
-- diferença de origem/qualidade da diretoria.

with api_por_dia as (

    select
        date(data_pedido) as data,
        count(*) as pedidos_api_count,
        sum(receita) as receita_api,
        round(countif(fk_cliente_valido) / count(*) * 100, 2) as pct_fk_cliente_valida_api,
        round(countif(fk_produto_valido) / count(*) * 100, 2) as pct_fk_produto_valida_api
    from {{ ref('fct_pedidos_api_candidato_alessandro') }}
    group by data

),

itens_por_dia as (

    select
        date(data_item) as data,
        count(*) as itens_pedido_count,
        sum(receita) as receita_itens_pedido,
        round(countif(fk_cliente_valido) / count(*) * 100, 2) as pct_fk_cliente_valida_itens,
        round(countif(fk_produto_valido) / count(*) * 100, 2) as pct_fk_produto_valida_itens
    from {{ ref('fct_itens_pedido_candidato_alessandro') }}
    group by data

)

select
    coalesce(a.data, i.data) as data,
    a.pedidos_api_count,
    a.receita_api,
    a.pct_fk_cliente_valida_api,
    a.pct_fk_produto_valida_api,
    i.itens_pedido_count,
    i.receita_itens_pedido,
    i.pct_fk_cliente_valida_itens,
    i.pct_fk_produto_valida_itens
from api_por_dia a
full outer join itens_por_dia i on a.data = i.data
