{{
  config(
    materialized='view'
  )
}}

-- Tipagem defensiva (ADR-009): ativo mistura duas convenções booleanas
-- ('0'/'1' e 'S'/'N') mais nulo; preco_tabela é TEXT, às vezes com
-- prefixo "R$ ". produto_id já é chave íntegra (achado do Dia 1), sem
-- necessidade de dedup.

with fonte as (

    select *
    from {{ source('raw', 'raw_produtos_candidato_alessandro') }}
    {{ ultima_particao('raw', 'raw_produtos_candidato_alessandro') }}

)

select
    produto_id,
    nome_produto,
    categoria,
    cast(regexp_extract(preco_tabela, r'[-+]?\d+(?:[.,]\d+)?') as numeric) as preco_tabela,
    case
        when ativo in ('1', 'S') then true
        when ativo in ('0', 'N') then false
        else null
    end as ativo
from fonte
