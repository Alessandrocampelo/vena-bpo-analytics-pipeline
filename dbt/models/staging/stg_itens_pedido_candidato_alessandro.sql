{{
  config(
    materialized='incremental',
    unique_key='item_id',
    incremental_strategy='merge',
  )
}}

-- Incremental por item_id (ADR-007/ADR-009): evita reprocessar as 5M
-- linhas via full-refresh a cada execução; MERGE idempotente mesmo se o
-- mesmo dia rodar duas vezes.
--
-- fk_cliente_valido é calculada contra TODO cliente_id que já existiu no
-- cadastro raw (int_clientes_bridge), não contra stg_clientes já
-- deduplicado por CPF (ADR-004) — um cliente_id que perdeu o desempate do
-- dedup ainda é um cliente real, só não é mais o "vencedor" da dimensão;
-- não pode virar FK inválida por causa disso. int_clientes_bridge também
-- carrega o cpf, que é o que liga cada item ao cliente deduplicado
-- (dim_cliente) no mart (Dia 5) — a FK de itens_pedido aponta pro
-- cliente_id bruto, não pro cpf. Promovido de CTE inline para modelo
-- próprio no Dia 5 (ADR-010) por ter ganho um segundo consumidor
-- (fct_pedidos_api).

with fonte as (

    select *
    from {{ source('raw', 'raw_itens_pedido_candidato_alessandro') }}
    {{ ultima_particao('raw', 'raw_itens_pedido_candidato_alessandro') }}

),

clientes_bridge as (

    select cliente_id, cpf
    from {{ ref('int_clientes_bridge_candidato_alessandro') }}

),

produtos as (

    select produto_id
    from {{ ref('stg_produtos_candidato_alessandro') }}

)

select
    f.item_id,
    f.pedido_id,
    f.cliente_id,
    f.produto_id,
    -- data_item vem como datetime completo ("2025-05-29 08:33:18"), não
    -- só data — SAFE_CAST(... AS DATE) falha silenciosamente pra esse
    -- formato e retornava NULL pra tudo (bug real do Dia 4, corrigido no
    -- Dia 5, ADR-010). SAFE_CAST(... AS DATETIME) aceita o formato.
    safe_cast(f.data_item as datetime) as data_item,
    f.quantidade,
    -- NUMERIC, não FLOAT64 (achado do Dia 5): dinheiro somado como ponto
    -- flutuante sobre milhões de linhas não é reprodutível bit-a-bit entre
    -- execuções (soma de float não é associativa) — quebrava a prova de
    -- idempotência de mart_saude_comercial (COUNT igual, checksum
    -- diferente). NUMERIC é decimal de ponto fixo, soma exata e
    -- determinística no BigQuery. Mesmo tratamento que stg_pedidos_api já
    -- tinha (ADR-009).
    cast(f.valor_unitario as numeric) as valor_unitario,
    cb.cpf as cliente_cpf,
    cb.cliente_id is not null as fk_cliente_valido,
    p.produto_id is not null as fk_produto_valido,
    f.quantidade is not null as quantidade_valida
from fonte f
left join clientes_bridge cb on f.cliente_id = cb.cliente_id
left join produtos p on f.produto_id = p.produto_id
