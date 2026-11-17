import os

import snowflake.connector

REQUIRED = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PRIVATE_KEY_FILE"]


def connect(config, role=None, warehouse=None, database=None, query_tag="pulse"):
    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"set these environment variables first: {', '.join(missing)}")
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        authenticator="SNOWFLAKE_JWT",
        private_key_file=os.environ["SNOWFLAKE_PRIVATE_KEY_FILE"],
        role=role or os.environ.get("SNOWFLAKE_ROLE"),
        warehouse=warehouse
        or os.environ.get("SNOWFLAKE_WAREHOUSE", config.snowflake.query_warehouse),
        database=database or config.snowflake.database,
        session_parameters={"QUERY_TAG": query_tag},
        client_session_keep_alive=False,
    )


def rows(conn, sql, params=None):
    with conn.cursor(snowflake.connector.DictCursor) as cur:
        cur.execute(sql, params)
        return [{k.lower(): v for k, v in row.items()} for row in cur.fetchall()]


def execute(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount
