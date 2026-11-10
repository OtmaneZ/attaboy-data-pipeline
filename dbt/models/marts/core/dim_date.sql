-- Calendrier : une ligne par jour, y compris les jours sans vente (fermetures).
with spine as (
    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('" ~ var('calendar_start') ~ "' as date)",
        end_date="cast('" ~ var('calendar_end') ~ "' as date)"
    ) }}
),

days as (
    select cast(date_day as date) as date_day
    from spine
)

select
    date_day,
    cast(extract(year from date_day) as integer) as year_number,
    cast(extract(month from date_day) as integer) as month_number,
    {{ french_month_name('extract(month from date_day)') }} as month_name,
    cast(date_trunc('month', date_day) as date) as month_start,
    cast(date_trunc('week', date_day) as date) as week_start,
    cast({{ iso_weekday('date_day') }} as integer) as iso_weekday,
    {{ french_weekday_name(iso_weekday('date_day')) }} as weekday_name,
    {{ iso_weekday('date_day') }} >= 6 as is_weekend
from days
