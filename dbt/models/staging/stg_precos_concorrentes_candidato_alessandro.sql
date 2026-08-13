{{
  config(
    materialized='view'
  )
}}

-- Exceção deliberada (ADR-009): diferente das demais fontes, uma cotação
-- de concorrente é um fato pontual no tempo, não um "estado atual" a ser
-- sobrescrito — preço varia legitimamente dia a dia, isso é o dado, não
-- sujeira. Por isso este modelo NÃO usa a macro ultima_particao(): lê
-- todas as partições raw acumuladas, com data_coleta marcando a origem
-- de cada linha. Sem dedup entre dias.

select
    date(_partitiontime) as data_coleta,
    produto_nome,
    categoria,
    cast(preco as numeric) as preco,
    concorrente,
    disponibilidade,
    (_parser_strategy = 'fallback') as linha_via_fallback
from {{ source('raw', 'raw_precos_concorrentes_candidato_alessandro') }}
