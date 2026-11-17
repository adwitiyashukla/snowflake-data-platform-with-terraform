create or replace dynamic table model.users (
    user_id varchar,
    org_id varchar,
    user_email varchar with tag ({{ database }}.governance.pii = 'email'),
    user_name varchar with tag ({{ database }}.governance.pii = 'name'),
    country varchar,
    first_seen timestamp_ntz,
    last_seen timestamp_ntz,
    last_device varchar,
    events number,
    session_count number
)
target_lag = '10 minutes'
warehouse = pulse_build_wh
refresh_mode = incremental
initialize = on_create
comment = 'one row per user with activity totals and the latest device seen'
with row access policy {{ database }}.governance.country_access on (country)
as
with latest as (
    select
        user_id,
        device
    from model.events
    where user_id is not null
    qualify row_number() over (partition by user_id order by event_ts desc, event_id asc) = 1
),

session_totals as (
    select
        user_id,
        count(*) as session_count
    from (
        select distinct
            user_id,
            session_id
        from model.events
        where user_id is not null and session_id is not null
    ) as distinct_sessions
    group by user_id
),

totals as (
    select
        user_id,
        min(org_id) as org_id,
        min(user_email) as user_email,
        min(user_name) as user_name,
        min(country) as country,
        min(event_ts) as first_seen,
        max(event_ts) as last_seen,
        count(*) as events
    from model.events
    where user_id is not null
    group by user_id
)

select
    totals.user_id,
    totals.org_id,
    totals.user_email,
    totals.user_name,
    totals.country,
    totals.first_seen,
    totals.last_seen,
    latest.device as last_device,
    totals.events,
    coalesce(session_totals.session_count, 0) as session_count
from totals
left join latest on totals.user_id = latest.user_id
left join session_totals on totals.user_id = session_totals.user_id;

create or replace dynamic table model.orgs (
    org_id varchar,
    country varchar,
    plan varchar,
    mrr_cents number,
    user_count number,
    first_seen timestamp_ntz,
    last_seen timestamp_ntz,
    events number
)
target_lag = '10 minutes'
warehouse = pulse_build_wh
refresh_mode = incremental
initialize = on_create
comment = 'one row per customer org with its current plan taken from the latest subscription event'
with row access policy {{ database }}.governance.country_access on (country)
as
with plans as (
    select
        org_id,
        plan,
        amount_cents
    from model.events
    where
        event_type in (
            'org_created',
            'subscription_started',
            'subscription_upgraded',
            'subscription_cancelled'
        )
    qualify row_number() over (partition by org_id order by event_ts desc, event_id asc) = 1
),

members as (
    select
        org_id,
        count(*) as user_count
    from (
        select distinct
            org_id,
            user_id
        from model.events
        where user_id is not null
    ) as distinct_members
    group by org_id
),

activity as (
    select
        org_id,
        min(country) as country,
        min(event_ts) as first_seen,
        max(event_ts) as last_seen,
        count(*) as events
    from model.events
    group by org_id
)

select
    activity.org_id,
    activity.country,
    coalesce(plans.plan, 'free') as plan,
    coalesce(plans.amount_cents, 0) as mrr_cents,
    coalesce(members.user_count, 0) as user_count,
    activity.first_seen,
    activity.last_seen,
    activity.events
from activity
left join plans on activity.org_id = plans.org_id
left join members on activity.org_id = members.org_id;
