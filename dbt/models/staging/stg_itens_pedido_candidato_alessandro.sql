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
-- cadastro raw (clientes_bridge), não contra stg_clientes já deduplicado
-- por CPF (ADR-004) — um cliente_id que perdeu o desempate do dedup ainda
-- é um cliente real, só não é mais o "vencedor" da dimensão; não pode virar
-- FK inválida por causa disso. clientes_bridge também carrega o cpf, que é
-- o que liga cada item ao cliente deduplicado (stg_clientes) no mart
-- (Dia 5) — a FK de itens_pedido aponta pro cliente_id bruto, não pro cpf.

with fonte as (

    select *
    from {{ source('raw', 'raw_itens_pedido_candidato_alessandro') }}
    {{ ultima_particao('raw', 'raw_itens_pedido_candidato_alessandro') }}

),

clientes_bridge as (

    select distinct cliente_id, cpf
    from {{ source('raw', 'raw_clientes_candidato_alessandro') }}
    {{ ultima_particao('raw', 'raw_clientes_candidato_alessandro') }}

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
    safe_cast(f.data_item as date) as data_item,
    f.quantidade,
    f.valor_unitario,
    cb.cpf as cliente_cpf,
    cb.cliente_id is not null as fk_cliente_valido,
    p.produto_id is not null as fk_produto_valido,
    f.quantidade is not null as quantidade_valida
from fonte f
left join clientes_bridge cb on f.cliente_id = cb.cliente_id
left join produtos p on f.produto_id = p.produto_id
