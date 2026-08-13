-- Garante que não há duas versões do mesmo CPF com janelas de validade
-- sobrepostas no snapshot SCD2 (scd_clientes_candidato_alessandro) —
-- prova formal de consistência do histórico (ADR-009), não só confiança
-- cega no mecanismo interno do dbt snapshot.

with janelas as (

    select
        cpf,
        dbt_valid_from,
        coalesce(dbt_valid_to, timestamp('9999-12-31')) as dbt_valid_to
    from {{ ref('scd_clientes_candidato_alessandro') }}

)

select
    a.cpf,
    a.dbt_valid_from as versao_a_inicio,
    a.dbt_valid_to as versao_a_fim,
    b.dbt_valid_from as versao_b_inicio,
    b.dbt_valid_to as versao_b_fim
from janelas a
join janelas b
    on a.cpf = b.cpf
    and a.dbt_valid_from < b.dbt_valid_from
    and a.dbt_valid_to > b.dbt_valid_from
