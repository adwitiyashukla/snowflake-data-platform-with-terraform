create or replace dynamic table model.daily_activity (
    event_date date,
    org_id varchar,
    country varchar,
    active_users number,
    session_count number,
    events number,
    feature_events number,
    page_views number
)
target_lag = '10 minutes'
warehouse = pulse_build_wh
refresh_mode = incremental
initialize = on_create
comment = 'activity per org per day'
with row access policy {{ database }}.governance.country_access on (country)
as
with counts as (
    select
        event_date,
        org_id,
        min(country) as country,
        count(*) as events,
        sum(iff(event_type = 'feature_used', 1, 0)) as feature_events,
        sum(iff(event_type = 'page_view', 1, 0)) as page_views
    from model.events
    group by event_date, org_id
),

active as (
    select
        event_date,
        org_id,
        count(*) as active_users
    from (
        select distinct
            event_date,
            org_id,
            user_id
        from model.events
        where user_id is not null
    ) as distinct_users
    group by event_date, org_id
),

session_totals as (
    select
        event_date,
        org_id,
        count(*) as session_count
    from (
        select distinct
            event_date,
            org_id,
            session_id
        from model.events
        where session_id is not null
    ) as distinct_sessions
    group by event_date, org_id
)

select
    counts.event_date,
    counts.org_id,
    counts.country,
    coalesce(active.active_users, 0) as active_users,
    coalesce(session_totals.session_count, 0) as session_count,
    counts.events,
    counts.feature_events,
    counts.page_views
from counts
left join active
    on counts.event_date = active.event_date and counts.org_id = active.org_id
left join session_totals
    on counts.event_date = session_totals.event_date and counts.org_id = session_totals.org_id;

create or replace dynamic table model.feature_daily (
    event_date date,
    feature varchar,
    org_count number,
    user_count number,
    events number,
    avg_duration_ms number
)
target_lag = '10 minutes'
warehouse = pulse_build_wh
refresh_mode = incremental
initialize = on_create
comment = 'feature usage per day, which is what product asks for most'
as
with usage as (
    select
        event_date,
        feature,
        count(*) as events,
        round(sum(duration_ms) / count(*)) as avg_duration_ms
    from model.events
    where event_type = 'feature_used' and feature is not null
    group by event_date, feature
),

org_totals as (
    select
        event_date,
        feature,
        count(*) as org_count
    from (
        select distinct
            event_date,
            feature,
            org_id
        from model.events
        where event_type = 'feature_used' and feature is not null
    ) as distinct_orgs
    group by event_date, feature
),

user_totals as (
    select
        event_date,
        feature,
        count(*) as user_count
    from (
        select distinct
            event_date,
            feature,
            user_id
        from model.events
        where event_type = 'feature_used' and feature is not null and user_id is not null
    ) as distinct_users
    group by event_date, feature
)

select
    usage.event_date,
    usage.feature,
    coalesce(org_totals.org_count, 0) as org_count,
    coalesce(user_totals.user_count, 0) as user_count,
    usage.events,
    usage.avg_duration_ms
from usage
left join org_totals
    on usage.event_date = org_totals.event_date and usage.feature = org_totals.feature
left join user_totals
    on usage.event_date = user_totals.event_date and usage.feature = user_totals.feature;

create or replace dynamic table model.revenue_daily (
    event_date date,
    payments_succeeded number,
    payments_failed number,
    amount_cents number,
    failed_amount_cents number,
    subscriptions_started number,
    subscriptions_cancelled number
)
target_lag = '10 minutes'
warehouse = pulse_build_wh
refresh_mode = incremental
initialize = on_create
comment = 'billing outcomes per day'
as
select
    event_date,
    sum(iff(event_type = 'payment_succeeded', 1, 0)) as payments_succeeded,
    sum(iff(event_type = 'payment_failed', 1, 0)) as payments_failed,
    sum(iff(event_type = 'payment_succeeded', amount_cents, 0)) as amount_cents,
    sum(iff(event_type = 'payment_failed', amount_cents, 0)) as failed_amount_cents,
    sum(iff(event_type = 'subscription_started', 1, 0)) as subscriptions_started,
    sum(iff(event_type = 'subscription_cancelled', 1, 0)) as subscriptions_cancelled
from model.events
where
    event_type in (
        'payment_succeeded',
        'payment_failed',
        'subscription_started',
        'subscription_cancelled'
    )
group by event_date;
