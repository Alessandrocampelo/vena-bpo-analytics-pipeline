-- Garante grão único por data em mart_saude_comercial (o FULL OUTER JOIN
-- por data no modelo já deveria garantir isso por construção; este teste
-- prova, não assume).

select data, count(*) as linhas
from {{ ref('mart_saude_comercial_candidato_alessandro') }}
group by data
having count(*) > 1
