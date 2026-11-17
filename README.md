# snowflake-data-platform-with-terraform

A Snowflake data platform for the product events of a SaaS app, built the way I would want it at a small startup. Terraform creates everything on the AWS and Snowflake side, Snowpipe loads gzipped JSON from S3 as it lands, dynamic tables build the model, PII is masked through tags and rows are filtered by country, schemachange runs the migrations, and GitHub Actions gives every pull request its own zero copy clone of the database to test against. The Python package is called pulse, and so are the database and the role prefix.

I built this to show what I can do with Snowflake and Terraform. Every number below comes from a real run on 16 November 2026 against a Snowflake trial account in AWS us-east-2 and a fresh AWS account.

## How the data flows

1. `pulse produce` simulates 14 days of events for 400 customer orgs (page views, feature use, sessions, signups, subscriptions, invoices) and writes them to S3 as gzipped ndjson under `events/dt=YYYY-MM-DD/`. It injects 0.5 percent duplicates a day late and switches to a second schema version with a locale field half way through, because real pipelines get both.
2. S3 sends an event notification to the SQS queue of the Snowpipe pipe. The pipe copies each file into `RAW.EVENTS`, one variant column per event plus file name, row number and load time.
3. `MODEL.EVENTS` is an incremental dynamic table that types the JSON, deduplicates on event id and carries the PII tags and the row access policy. Its lag is `downstream`, so it refreshes only when the five tables that read from it need it.
4. `USERS`, `ORGS`, `DAILY_ACTIVITY`, `FEATURE_DAILY` and `REVENUE_DAILY` are incremental dynamic tables with a 10 minute lag.
5. `pulse ops` reports Snowpipe latency, credits per million events, warehouse sizing and dynamic table health from the account's own history functions.

## Numbers from the run

| what | measured |
| --- | --- |
| events produced | 305,843 events in 39 files, 19.2 MB gzipped, uploaded in 36.8 s |
| Snowpipe | 39 of 39 files loaded, 0 errors, p50 35.0 s, p95 58.0 s, max 66.0 s from S3 write to row loaded |
| deduplication | 304,509 events kept from 305,843 raw rows (1,334 duplicates dropped) |
| migrations | 4 schemachange scripts in 28 s on an X-Small warehouse, including the first refresh of all six dynamic tables |
| full refresh of the model | 3.18 s for 6 tables on PULSE, 2.68 s on the clone |
| pull request environment | clone of the whole database in 9.76 s, migrations skipped as already applied, 9 checks passed, dropped in 0.46 s |
| credits for the whole first day | 0.29 credits (0.16 build, 0.13 query), which is 0.96 credits or 2.87 USD per million events at 3 USD per credit |
| governance | 5 columns tagged as PII, 1 masking policy on the tag, row access policy on 4 tables |
| terraform | 80 resources in the platform root (48 of them grants), 3 in the state root |
| tests | 52 pytest tests, all passing |

The credits line counts warehouse time only. PIPE_USAGE_HISTORY had not caught up yet when I ran the report, so the Snowpipe part shows 0 and the real number is a bit higher.

## What Terraform creates

Two roots. `terraform/state` makes the versioned S3 bucket that holds the state of the second root, with S3 native locking. `terraform/platform` does the rest with the hashicorp/aws and snowflakedb/snowflake providers.

On the AWS side it creates the landing bucket (public access blocked, files expire after 30 days), an IAM role that trusts the IAM user of the Snowflake storage integration with its external id, a read only policy on the events prefix, and the bucket notification pointed at the SQS queue of the pipe. It waits 20 seconds after the IAM role before creating the pipe, because Snowflake assumes the role at create time and IAM takes a moment to propagate.

On the Snowflake side it creates the database with RAW, MODEL, GOVERNANCE and SCHEMACHANGE schemas, three X-Small warehouses that suspend after 60 seconds, each with its own daily resource monitor (2, 5 and 5 credits), the storage integration, the external stage, the landing table with change tracking, the auto ingest pipe, the roles, the grants and two service users with key pair auth. There are no passwords anywhere.

Roles come in two layers. Access roles own privileges (`PULSE_RAW_READ`, `PULSE_MODEL_READ`, `PULSE_MODEL_WRITE`) and functional roles are what people and jobs log in with (`PULSE_DEPLOYER`, `PULSE_ANALYST`, `PULSE_ANALYST_EU`, `PULSE_PII_READER`, `PULSE_OPS`). Terraform itself runs as `PULSE_TERRAFORM`, a service user created once by `bootstrap.sql`, and switches to ACCOUNTADMIN only for warehouses, resource monitors and the SNOWFLAKE database roles.

## Governance

`V1.0.0__governance.sql` creates a `pii` tag with the allowed values email, name and ip, and a masking policy attached to the tag itself. Any column tagged `pii` is masked on read unless `PULSE_PII_READER` is in the session. Emails keep their domain, IPs lose their last octet, names become `***`. The dynamic tables tag their columns inline, so a new PII column is masked the moment it is created.

The row access policy `country_access` filters rows through a mapping table. `PULSE_ANALYST` is mapped to `*` and sees every row with PII masked, `PULSE_ANALYST_EU` is mapped to DE, FR, NL, SE and ES. `PULSE_PII_READER` is granted to the deployer so that dynamic table refreshes, which run as the owner, store real values and full rows instead of masked ones.

## Migrations and pull request environments

Migrations are plain SQL files run by schemachange, with `{{ database }}` as the only variable so the same files run against PULSE and against a clone. The change history table lives in the SCHEMACHANGE schema of whichever database is targeted.

On a pull request the workflow runs `pulse env create --pr N`, which is `create database PULSE_PR_N clone PULSE`, then schemachange against the clone, then `pulse env check`, then drops the clone whether the checks passed or not. The checks resume and refresh the cloned dynamic tables, then verify that all six tables exist and are active, that raw rows loaded, that event ids are unique, that the PII columns are tagged, that the masking policy is on the tag, that the row access policy is attached and that the change history holds successful scripts. On a push to main the same deploy and check run against PULSE. Both jobs are gated by a `PULSE_LIVE` repository variable, so the repo still lints and tests without an account.

## The ops CLI

`pulse ops latency` joins COPY_HISTORY with the S3 object timestamps and prints p50, p95 and max seconds from write to load, plus the pipe status. `pulse ops credits` adds WAREHOUSE_METERING_HISTORY and PIPE_USAGE_HISTORY and divides by the rows in the landing table. `pulse ops warehouses` combines metering, WAREHOUSE_LOAD_HISTORY and QUERY_HISTORY_BY_WAREHOUSE and gives each warehouse a verdict: auto suspend too long, queueing, unused in the window, or fine. `pulse ops tables` reads DYNAMIC_TABLE_REFRESH_HISTORY and shows refreshes in the last day, how many of them were incremental, and rows inserted and deleted.

The ops user has MONITOR on the pipe, the warehouses and the dynamic tables plus the USAGE_VIEWER and OBJECT_VIEWER database roles, and nothing else.

## Running it

You need Terraform 1.10 or newer, Python 3.12, the AWS CLI configured with an admin user in the same region as your Snowflake account, and ACCOUNTADMIN on a Snowflake account (Enterprise edition for tags and policies, which the trial gives you).

```
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\pulse keygen terraform
.venv\Scripts\pulse keygen deployer
.venv\Scripts\pulse keygen ops
```

Paste the terraform public key into `bootstrap.sql` and run it in Snowsight as ACCOUNTADMIN. Then set the variables Terraform needs and apply both roots:

```
set TF_VAR_snowflake_organization=<org>
set TF_VAR_snowflake_account=<account>
set TF_VAR_snowflake_user=PULSE_TERRAFORM
set TF_VAR_snowflake_private_key_path=C:/Users/you/.pulse/terraform.p8
set TF_VAR_deployer_public_key=<one line printed by keygen>
set TF_VAR_ops_public_key=<one line printed by keygen>
terraform -chdir=terraform/state init
terraform -chdir=terraform/state apply
terraform -chdir=terraform/platform init -backend-config="bucket=<bucket from the first apply>" -backend-config="region=us-east-2"
terraform -chdir=terraform/platform apply
```

Keep the SNOWFLAKE_* variables unset while Terraform runs. The provider picks them up, and the warehouse they name does not exist yet. For the CLI and schemachange set them per user:

```
set SNOWFLAKE_ACCOUNT=<org>-<account>
set SNOWFLAKE_USER=PULSE_DEPLOYER
set SNOWFLAKE_ROLE=PULSE_DEPLOYER
set SNOWFLAKE_WAREHOUSE=PULSE_BUILD_WH
set SNOWFLAKE_DATABASE=PULSE
set SNOWFLAKE_AUTHENTICATOR=snowflake_jwt
set SNOWFLAKE_PRIVATE_KEY_FILE=C:\Users\you\.pulse\deployer.p8
.venv\Scripts\pulse produce
.venv\Scripts\schemachange deploy
.venv\Scripts\pulse env check --name PULSE
```

Switch the user, role, key and warehouse to PULSE_OPS and PULSE_QUERY_WH for the `pulse ops` reports. For GitHub Actions add the secrets `SNOWFLAKE_ACCOUNT` and `SNOWFLAKE_DEPLOYER_KEY` (the contents of the private key file) and the variable `PULSE_LIVE=true`.

Everything tunable sits in `config.toml` and is validated on load: region and bucket prefix, database and warehouse names, the seed, size and duplicate rate of the producer, the credit price and the ops thresholds.

## Tests and checks

`pytest` runs 52 tests without any account. The dynamic table SQL is transpiled to DuckDB with sqlglot and run over events from the same simulator, so dedup counts, daily totals and revenue are checked against what the simulation knows it generated. The Terraform files are parsed with python-hcl2 to check that every variable, local and resource reference resolves, that the preview resources are enabled on the provider and that the names Terraform creates match `config.toml` and the migrations. The producer is tested against moto. CI also runs ruff, sqlfluff with the Snowflake dialect, and terraform fmt and validate for both roots, and I ran actionlint on the workflow.

## Layout

```
pulse/                     cli, config, event simulator, producer, env (clones and checks), ops reports, key generation
migrations/                four schemachange scripts
terraform/state/           the state bucket
terraform/platform/        everything else
tests/                     52 tests
bootstrap.sql              the one script run by hand as ACCOUNTADMIN
config.toml                every tunable
.github/workflows/ci.yml   lint, test, pr-environment, deploy
```
