{{
  config(
    materialized='table'
  )
}}

-- Decisão de apresentação para BI (ADR-010): categoria nula vira
-- 'Não informado' (achado real: 165/800 produtos sem categoria).
-- status_ativo é uma coluna de leitura direta para BI; o booleano ativo
-- original (já tipado na staging, ADR-009) é mantido também.

select
    produto_id,
    nome_produto,
    coalesce(categoria, 'Não informado') as categoria,
    preco_tabela,
    ativo,
    case
        when ativo is null then 'Não informado'
        when ativo then 'Ativo'
        else 'Inativo'
    end as status_ativo
from {{ ref('stg_produtos_candidato_alessandro') }}
