use role accountadmin;

create role if not exists pulse_terraform
comment = 'runs terraform/platform, everything else is created by it';

grant role sysadmin to role pulse_terraform;
grant role useradmin to role pulse_terraform;
grant manage grants on account to role pulse_terraform;
grant create integration on account to role pulse_terraform;
grant create network policy on account to role pulse_terraform;

create user if not exists pulse_terraform
    type = service
    default_role = pulse_terraform
    rsa_public_key = '<PUBLIC_KEY_ONE_LINE>'
    comment = 'terraform service user';

grant role pulse_terraform to user pulse_terraform;
grant role accountadmin to user pulse_terraform;
