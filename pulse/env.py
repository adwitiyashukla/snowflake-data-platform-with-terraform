import re
import time

from pulse.snow import execute, rows

NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


def env_name(config, pr=None, name=None):
    if name:
        if not NAME.match(name):
            raise SystemExit(f"bad environment name {name}")
        return name
    if pr is None:
        raise SystemExit("give --pr or --name")
    return f"{config.snowflake.database}_PR_{int(pr)}"


def timed(fn):
    started = time.monotonic()
    result = fn()
    return result, round(time.monotonic() - started, 2)


def create(conn, config, name):
    source = config.snowflake.database
    _, seconds = timed(lambda: execute(conn, f"create database {name} clone {source}"))
    return seconds


def drop(conn, name):
    _, seconds = timed(lambda: execute(conn, f"drop database if exists {name}"))
    return seconds


def dynamic_tables(conn, config, name):
    schema = config.snowflake.model_schema
    listed = rows(conn, f"show dynamic tables in schema {name}.{schema}")
    ordered = sorted(listed, key=lambda row: (row["name"] != "EVENTS", row["name"]))
    return [
        {
            "name": row["name"],
            "state": row["scheduling_state"],
            "target_lag": row["target_lag"],
            "refresh_mode": row["refresh_mode"],
        }
        for row in ordered
    ]


def refresh(conn, config, name):
    schema = config.snowflake.model_schema
    tables = dynamic_tables(conn, config, name)
    names = [f"{name}.{schema}.{table['name']}" for table in tables]
    for full in names:
        execute(conn, f"alter dynamic table {full} resume")
    _, seconds = timed(lambda: execute(conn, f"alter dynamic table {', '.join(names)} refresh"))
    return tables, seconds


def policy_references(conn, config, name, policy):
    schema = config.snowflake.governance_schema
    return rows(
        conn,
        f"select ref_entity_name, ref_column_name, policy_kind "
        f"from table({name}.information_schema.policy_references("
        f"policy_name => '{name}.{schema}.{policy}'))",
    )


def tagged_columns(conn, config, name, table):
    full = f"{name}.{config.snowflake.model_schema}.{table}"
    return rows(
        conn,
        f"select count(*) as n from table({name}.information_schema.tag_references_all_columns("
        f"'{full}', 'table')) where tag_name = 'PII'",
    )[0]["n"]


def check(conn, config, name, expected_tables):
    sf = config.snowflake
    results = []

    def add(label, ok, detail):
        results.append({"check": label, "ok": bool(ok), "detail": detail})

    tables, seconds = refresh(conn, config, name)
    names = {table["name"] for table in tables}
    missing = sorted(set(expected_tables) - names)
    add(
        "dynamic tables present",
        not missing,
        f"missing {missing}" if missing else f"{len(names)} tables",
    )
    inactive = [
        table["name"] for table in dynamic_tables(conn, config, name) if table["state"] != "ACTIVE"
    ]
    add("dynamic tables active", not inactive, f"inactive {inactive}" if inactive else "all active")
    add("refresh completed", True, f"{seconds}s for {len(names)} tables")

    raw = rows(conn, f"select count(*) as n from {name}.{sf.raw_schema}.{sf.raw_table}")[0]["n"]
    model = rows(
        conn,
        f"select count(*) as n, count(distinct event_id) as ids "
        f"from {name}.{sf.model_schema}.events",
    )[0]
    add("raw rows loaded", raw > 0, f"{raw} raw rows")
    add(
        "events deduplicated",
        model["n"] == model["ids"] and model["n"] <= raw,
        f"{model['n']} events from {raw} raw rows",
    )

    tagged = sum(tagged_columns(conn, config, name, table) for table in ("EVENTS", "USERS"))
    add("pii columns tagged", tagged >= 5, f"{tagged} columns")
    masking = policy_references(conn, config, name, "MASK_PII")
    add("masking policy on tag", len(masking) >= 1, f"{len(masking)} references")
    guarded = policy_references(conn, config, name, "COUNTRY_ACCESS")
    guarded_tables = sorted({row["ref_entity_name"] for row in guarded})
    add("row access policy attached", len(guarded_tables) >= 3, f"{len(guarded_tables)} tables")

    history = rows(
        conn,
        f"select count(*) as n from {name}.schemachange.change_history where status = 'Success'",
    )[0]["n"]
    add("change history recorded", history > 0, f"{history} successful scripts")
    return results


def format_results(results):
    width = max(len(row["check"]) for row in results)
    lines = []
    for row in results:
        mark = "ok  " if row["ok"] else "FAIL"
        lines.append(f"{mark} {row['check'].ljust(width)}  {row['detail']}")
    return "\n".join(lines)
