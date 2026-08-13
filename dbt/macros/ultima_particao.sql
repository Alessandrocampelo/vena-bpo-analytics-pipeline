{% macro ultima_particao(source_name, table_name) %}
{#
  Filtro reutilizado por todo modelo de staging que lê uma fonte "estado
  atual completo" (clientes, produtos, itens_pedido, pedidos_api) — cada
  partição raw já contém o dado completo da fonte naquele dia (ADR-008),
  então staging não deve fazer UNION de partições históricas, só ler a
  mais recente (ADR-009). Não usado por stg_precos_concorrentes, que é a
  exceção deliberada (histórico append-only).
#}
  where date(_partitiontime) = (
    select max(date(_partitiontime))
    from {{ source(source_name, table_name) }}
  )
{% endmacro %}
