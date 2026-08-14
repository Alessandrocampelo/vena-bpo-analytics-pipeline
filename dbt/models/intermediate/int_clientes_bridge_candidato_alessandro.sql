{{
  config(
    materialized='view'
  )
}}

-- Promovido de CTE inline dentro de stg_itens_pedido (Etapa 4) para modelo
-- próprio agora que tem um segundo consumidor (fct_pedidos_api, Etapa 5) —
-- ADR-010. Cobre todo o universo de raw_clientes, não só os
-- sobreviventes do dedup por CPF (ADR-009): um cliente_id "perdedor" do
-- dedup ainda é um cliente real, só não é mais o vencedor da dimensão.

select distinct cliente_id, cpf
from {{ source('raw', 'raw_clientes_candidato_alessandro') }}
{{ ultima_particao('raw', 'raw_clientes_candidato_alessandro') }}
