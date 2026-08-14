{{
  config(
    materialized='table'
  )
}}

-- Fatia atual do snapshot SCD2 (ADR-010) — dbt_valid_to is null é a versão
-- vigente de cada CPF. Decisão de apresentação para BI, adiada da ADR-004:
-- estado/segmento nulos viram 'Não informado' só aqui — a staging
-- continua guardando NULL de verdade, mart é a única camada que decide
-- apresentação.

select
    cpf,
    cliente_id,
    nome,
    email,
    cidade,
    coalesce(estado, 'Não informado') as estado,
    data_cadastro,
    coalesce(segmento, 'Não informado') as segmento
from {{ ref('scd_clientes_candidato_alessandro') }}
where dbt_valid_to is null
