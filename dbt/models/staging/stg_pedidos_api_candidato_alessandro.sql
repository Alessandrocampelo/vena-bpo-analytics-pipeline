{{
  config(
    materialized='incremental',
    unique_key='pedido_id',
    incremental_strategy='merge',
  )
}}

-- Incremental por pedido_id (ADR-007): a API sempre devolve o estado
-- atual completo (48k linhas) a cada pull, então um MERGE simples (sem
-- guarda condicional extra) já implementa o upsert certo — updated_at do
-- pull mais recente nunca regride em relação ao anterior, é sempre o
-- estado corrente reportado pelo servidor. Isso captura transição de
-- status (pago -> cancelado/reembolsado) de pedidos já carregados antes,
-- sem duplicar (achado da Etapa 1: updated_at avança quando o status muda).
--
-- Tipagem defensiva reforçada aqui (não confiar só na normalização já
-- feita na ingestão, Etapa 2, de "593.57 BRL" -> 593.57): staging nunca
-- assume que o raw chegou limpo.
--
-- Achado da Etapa 5: 235/48.000 linhas (0,49%) têm data_pedido em formato
-- "DD/MM/YYYY" em vez do ISO 8601 do resto (mesma classe de problema do
-- enunciado — "campos em formatos inconsistentes" — só que nesta coluna,
-- não em valor_unitario). SAFE_CAST sozinho retorna NULL silenciosamente
-- pra essas linhas; corrigido com um segundo parse via
-- SAFE.PARSE_TIMESTAMP no formato brasileiro, coalescendo os dois.

with fonte as (

    select *
    from {{ source('raw', 'raw_pedidos_api_candidato_alessandro') }}
    {{ ultima_particao('raw', 'raw_pedidos_api_candidato_alessandro') }}

)

select
    pedido_id,
    cliente_id,
    produto_id,
    coalesce(
        safe_cast(data_pedido as timestamp),
        safe.parse_timestamp('%d/%m/%Y', data_pedido)
    ) as data_pedido,
    safe_cast(updated_at as timestamp) as updated_at,
    status,
    quantidade,
    safe_cast(valor_unitario as numeric) as valor_unitario
from fonte
