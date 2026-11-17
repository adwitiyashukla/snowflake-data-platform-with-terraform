use schema {{ database }}.governance;

create tag if not exists pii
allowed_values 'email', 'name', 'ip'
comment = 'marks columns that hold personal data';

create table if not exists country_grants (
    role_name varchar not null,
    country varchar not null
);

merge into country_grants as target
using (
    select
        column1 as role_name,
        column2 as country
    from
        values
        ('PULSE_ANALYST', '*'),
        ('PULSE_ANALYST_EU', 'DE'),
        ('PULSE_ANALYST_EU', 'FR'),
        ('PULSE_ANALYST_EU', 'NL'),
        ('PULSE_ANALYST_EU', 'SE'),
        ('PULSE_ANALYST_EU', 'ES')
) as source
    on target.role_name = source.role_name and target.country = source.country
when not matched then insert (role_name, country) values (source.role_name, source.country);

create or replace masking policy mask_pii as(val varchar) returns varchar ->
case
    when is_role_in_session('PULSE_PII_READER') then val
    when val is null then val
    when system$get_tag_on_current_column('{{ database }}.governance.pii') = 'email'
        then regexp_replace(val, '^[^@]+', '***')
    when system$get_tag_on_current_column('{{ database }}.governance.pii') = 'ip'
        then regexp_replace(val, '[0-9]+$', '0')
    else '***'
end;

alter tag pii set masking policy mask_pii;

create or replace row access policy country_access as(row_country varchar) returns boolean ->
is_role_in_session('PULSE_PII_READER')
or exists (
    select 1
    from {{ database }}.governance.country_grants as grant_row
    where
        grant_row.country in (row_country, '*')
        and is_role_in_session(grant_row.role_name)
);
