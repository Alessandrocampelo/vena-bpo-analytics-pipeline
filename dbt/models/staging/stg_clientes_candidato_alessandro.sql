{{
  config(
    materialized='view'
  )
}}

-- Dedup por CPF, não por cliente_id (ADR-004): CPF duplica mais (185)
-- que cliente_id (12) nos dados reais — CPF é a identidade de negócio.
-- Critério de desempate: linha com mais campos não nulos (completude);
-- em empate, data_cadastro mais recente.

with fonte as (

    select *
    from {{ source('raw', 'raw_clientes_candidato_alessandro') }}
    {{ ultima_particao('raw', 'raw_clientes_candidato_alessandro') }}

),

com_completude as (

    select
        *,
        (
            (case when nome is not null then 1 else 0 end)
            + (case when email is not null then 1 else 0 end)
            + (case when cidade is not null then 1 else 0 end)
            + (case when estado is not null then 1 else 0 end)
            + (case when data_cadastro is not null then 1 else 0 end)
            + (case when segmento is not null then 1 else 0 end)
        ) as completude
    from fonte

),

ranqueado as (

    select
        *,
        row_number() over (
            partition by cpf
            order by completude desc, data_cadastro desc
        ) as posicao_dedup
    from com_completude

)

select
    cliente_id,
    nome,
    cpf,
    email,
    cidade,
    estado,
    safe_cast(data_cadastro as date) as data_cadastro,
    segmento
from ranqueado
where posicao_dedup = 1
