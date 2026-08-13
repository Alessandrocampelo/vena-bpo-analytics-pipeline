{% snapshot scd_clientes_candidato_alessandro %}

{{
    config(
      target_schema=env_var('BQ_DATASET'),
      unique_key='cpf',
      strategy='check',
      check_cols=['nome', 'email', 'cidade', 'estado', 'segmento'],
    )
}}

-- SCD2 do histórico de cliente (requisito obrigatório do teste). Estratégia
-- 'check' em vez de 'timestamp' porque clientes não tem coluna de última
-- atualização confiável — data_cadastro é a data do cadastro original, não
-- muda quando um campo é editado (ADR-009). cliente_id fica fora de
-- check_cols de propósito: é atributo técnico de rastreamento (ADR-004),
-- não conteúdo de negócio — sua troca não deve abrir uma nova versão.

select
    cliente_id,
    nome,
    cpf,
    email,
    cidade,
    estado,
    data_cadastro,
    segmento
from {{ ref('stg_clientes_candidato_alessandro') }}

{% endsnapshot %}
