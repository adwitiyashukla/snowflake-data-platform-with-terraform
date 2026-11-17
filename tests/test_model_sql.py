import collections
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import pytest
import sqlglot

from pulse.events import PLAN_PRICE, Simulation

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
TABLE = re.compile(
    r"create or replace dynamic table model\.(\w+) \(.*?\n\)\n.*?\nas\n(.*?);\n(?=\n|$)", re.S
)


def model_queries():
    found = []
    for path in sorted(MIGRATIONS.glob("V*.sql")):
        text = path.read_text().replace("{{ database }}", "pulse")
        for name, query in TABLE.findall(text):
            found.append((name, query))
    return found


def to_duckdb(query):
    sql = sqlglot.transpile(query, read="snowflake", write="duckdb")[0]
    return re.sub(r"record -> '", "record ->> '", sql)


@pytest.fixture(scope="module")
def world():
    sim = Simulation(3, date(2026, 9, 1), 4, 40, 0.02, 2)
    conn = duckdb.connect()
    conn.execute("create schema raw")
    conn.execute("create schema model")
    conn.execute(
        "create table raw.events (record json, file_name varchar, "
        "file_row_number integer, loaded_at timestamp)"
    )
    events = []
    loaded = datetime(2026, 9, 20, 12, 0, 0)
    for key, batch in sim.files(500, "events/"):
        loaded += timedelta(minutes=1)
        conn.executemany(
            "insert into raw.events values (?, ?, ?, ?)",
            [(json.dumps(item), key, i + 1, loaded) for i, item in enumerate(batch)],
        )
        events.extend(batch)
    for name, query in model_queries():
        conn.execute(f"create table model.{name} as {to_duckdb(query)}")
    return sim, conn, events


def one(conn, sql):
    return conn.execute(sql).fetchone()[0]


def test_every_dynamic_table_was_found():
    names = [name for name, _ in model_queries()]
    assert names == ["events", "users", "orgs", "daily_activity", "feature_daily", "revenue_daily"]


def test_events_are_deduplicated_and_typed(world):
    sim, conn, events = world
    distinct = {item["event_id"] for item in events}
    assert len(events) > len(distinct)
    assert one(conn, "select count(*) from model.events") == len(distinct)
    assert one(conn, "select count(distinct event_id) from model.events") == len(distinct)
    assert one(conn, "select count(*) from model.events where event_ts is null") == 0
    assert one(conn, "select count(*) from model.events where country is null") == 0
    first = min(events, key=lambda item: item["event_ts"])
    row = conn.execute(
        "select event_ts, user_email, schema_version from model.events where event_id = ?",
        [first["event_id"]],
    ).fetchone()
    assert (
        row[0].strftime("%Y-%m-%dT%H:%M:%S.") + f"{row[0].microsecond // 1000:03d}Z"
        == first["event_ts"]
    )
    assert row[1] == (first["user"] or {}).get("email")
    assert row[2] == first["schema_version"]


def test_users_match_the_generated_people(world):
    sim, conn, events = world
    seen = collections.defaultdict(set)
    for item in events:
        if item["user_id"]:
            seen[item["user_id"]].add(item["session_id"])
    assert one(conn, "select count(*) from model.users") == len(seen)
    rows = conn.execute("select user_id, session_count, events from model.users").fetchall()
    per_user = collections.Counter(item["event_id"] for item in events)
    unique_events = collections.defaultdict(set)
    for item in events:
        if item["user_id"]:
            unique_events[item["user_id"]].add(item["event_id"])
    for user_id, sessions, count in rows:
        assert sessions == len({s for s in seen[user_id] if s})
        assert count == len(unique_events[user_id])
    assert sum(per_user.values()) >= len(per_user)


def test_orgs_carry_the_latest_plan(world):
    sim, conn, events = world
    rows = conn.execute("select org_id, plan, mrr_cents, user_count from model.orgs").fetchall()
    by_id = {org["org_id"]: org for org in sim.orgs}
    assert len(rows) == sum(1 for org in sim.orgs if org["announced"])
    members = collections.defaultdict(set)
    for item in events:
        if item["user_id"]:
            members[item["org_id"]].add(item["user_id"])
    for org_id, plan, mrr, users in rows:
        assert plan == by_id[org_id]["plan"]
        assert mrr == PLAN_PRICE[plan]
        assert users == len(members[org_id])


def test_daily_activity_adds_up(world):
    sim, conn, events = world
    distinct = {item["event_id"]: item for item in events}.values()
    expected = collections.defaultdict(lambda: {"events": 0, "users": set()})
    for item in distinct:
        key = (item["event_ts"][:10], item["org_id"])
        expected[key]["events"] += 1
        if item["user_id"]:
            expected[key]["users"].add(item["user_id"])
    rows = conn.execute(
        "select cast(event_date as varchar), org_id, events, active_users from model.daily_activity"
    ).fetchall()
    assert len(rows) == len(expected)
    for day, org_id, count, active in rows:
        assert count == expected[(day, org_id)]["events"]
        assert active == len(expected[(day, org_id)]["users"])
    assert one(conn, "select sum(events) from model.daily_activity") == len(distinct)


def test_revenue_and_features_reconcile(world):
    sim, conn, events = world
    distinct = {item["event_id"]: item for item in events}.values()
    paid = sum(
        item["properties"]["amount_cents"]
        for item in distinct
        if item["event_type"] == "payment_succeeded"
    )
    assert one(conn, "select coalesce(sum(amount_cents), 0) from model.revenue_daily") == paid
    features = sum(1 for item in distinct if item["event_type"] == "feature_used")
    assert one(conn, "select sum(events) from model.feature_daily") == features
    assert one(conn, "select count(*) from model.feature_daily where avg_duration_ms is null") == 0
