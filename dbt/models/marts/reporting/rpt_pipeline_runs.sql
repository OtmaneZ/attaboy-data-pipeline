-- Journal des exécutions du pipeline, du plus récent au plus ancien.
select
    run_id,
    pipeline_name,
    started_at,
    finished_at,
    status,
    rows_processed,
    -- Ligne longue une fois la macro développée par l'adaptateur, pas dans le source.
    {{ dbt.datediff('started_at', 'finished_at', 'second') }} as duration_seconds, -- noqa: LT05
    error_message
from {{ source('meta', 'pipeline_runs') }}
