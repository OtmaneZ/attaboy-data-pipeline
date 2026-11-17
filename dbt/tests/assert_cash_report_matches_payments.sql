-- Le rapport de caisse ne doit ni perdre ni inventer d'argent par rapport aux paiements et remboursements.
with report as (
    select
        sum(amount_paid) as amount_paid,
        sum(amount_refunded) as amount_refunded
    from {{ ref('rpt_payments_daily') }}
),

facts as (
    select
        (select coalesce(sum(total_paid), 0) from {{ ref('fct_payments') }}) as amount_paid,
        (select coalesce(sum(total_refunded), 0) from {{ ref('fct_refunds') }}) as amount_refunded
)

select
    report.amount_paid,
    facts.amount_paid as expected_paid,
    report.amount_refunded,
    facts.amount_refunded as expected_refunded
from report
cross join facts
where
    report.amount_paid <> facts.amount_paid
    or report.amount_refunded <> facts.amount_refunded
