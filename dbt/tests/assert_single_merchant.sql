-- Isolement démo / réel : une base ne contient qu'un seul marchand Clover.
-- Si des données simulées (DEMOPIZZERIA1) côtoient des données réelles, ce test échoue
-- avant qu'un chiffre mélangé n'atteigne le tableau de bord.
select
    count(distinct merchant_id) as merchants
from {{ source('clover', 'raw_clover_orders') }}
having count(distinct merchant_id) > 1
