{{ config(severity='warn') }}

-- Reporta (não bloqueia o build) se a taxa de FK inválida em itens_pedido
-- sair muito do range observado no Dia 1 (~1,50% cliente, ~1,49%
-- produto) — sinal de mudança na fonte a investigar, não motivo para
-- falhar o pipeline (ADR-005: sinalizar, nunca descartar/bloquear por
-- causa de uma sujeira já esperada e conhecida). Severity 'warn' garante
-- que este teste nunca derruba o `dbt build`, só alerta.

select
    'fk_cliente_invalido' as metrica,
    round(countif(not fk_cliente_valido) / count(*) * 100, 2) as taxa_pct
from {{ ref('stg_itens_pedido_candidato_alessandro') }}
having taxa_pct > 5.0

union all

select
    'fk_produto_invalido' as metrica,
    round(countif(not fk_produto_valido) / count(*) * 100, 2) as taxa_pct
from {{ ref('stg_itens_pedido_candidato_alessandro') }}
having taxa_pct > 5.0
