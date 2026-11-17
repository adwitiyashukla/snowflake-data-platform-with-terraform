create or replace dynamic table model.events (
    event_id varchar,
    event_type varchar,
    event_ts timestamp_ntz,
    event_date date,
    org_id varchar,
    user_id varchar,
    session_id varchar,
    user_email varchar with tag ({{ database }}.governance.pii = 'email'),
    user_name varchar with tag ({{ database }}.governance.pii = 'name'),
    ip varchar with tag ({{ database }}.governance.pii = 'ip'),
    country varchar,
    device varchar,
    locale varchar,
    plan varchar,
    feature varchar,
    page varchar,
    amount_cents number,
    duration_ms number,
    schema_version number,
    file_name varchar,
    loaded_at timestamp_ntz
)
target_lag = downstream
warehouse = pulse_build_wh
refresh_mode = incremental
initialize = on_create
comment = 'one row per event, typed from the raw json and deduplicated on event_id'
with row access policy {{ database }}.governance.country_access on (country)
as
select
    record:event_id::varchar as event_id,
    record:event_type::varchar as event_type,
    record:event_ts::timestamp_ntz as event_ts,
    record:event_ts::timestamp_ntz::date as event_date,
    record:org_id::varchar as org_id,
    record:user_id::varchar as user_id,
    record:session_id::varchar as session_id,
    record:user.email::varchar as user_email,
    record:user.name::varchar as user_name,
    record:context.ip::varchar as ip,
    record:context.country::varchar as country,
    record:context.device::varchar as device,
    record:context.locale::varchar as locale,
    record:properties.plan::varchar as plan,
    record:properties.feature::varchar as feature,
    record:properties.page::varchar as page,
    record:properties.amount_cents::number as amount_cents,
    record:properties.duration_ms::number as duration_ms,
    record:schema_version::number as schema_version,
    file_name,
    loaded_at
from raw.events
where record:event_id is not null
qualify row_number() over (
    partition by record:event_id::varchar
    order by loaded_at asc, file_name asc, file_row_number asc
) = 1;
