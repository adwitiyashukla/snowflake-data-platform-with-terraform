import pytest

from pulse import env

TABLES = ["EVENTS", "USERS", "ORGS", "DAILY_ACTIVITY", "FEATURE_DAILY", "REVENUE_DAILY"]


def show_rows(state="ACTIVE"):
    return [
        {
            "NAME": name,
            "SCHEDULING_STATE": state,
            "TARGET_LAG": "10 minutes",
            "REFRESH_MODE": "INCREMENTAL",
        }
        for name in ["USERS", "EVENTS", "ORGS", "DAILY_ACTIVITY", "FEATURE_DAILY", "REVENUE_DAILY"]
    ]


def test_env_name_from_pr_or_explicit(cfg):
    assert env.env_name(cfg, pr=42) == "PULSE_PR_42"
    assert env.env_name(cfg, name="PULSE_STAGING") == "PULSE_STAGING"
    with pytest.raises(SystemExit):
        env.env_name(cfg, name="drop database x")
    with pytest.raises(SystemExit):
        env.env_name(cfg)


def test_create_and_drop_issue_clone_statements(cfg, fake_conn):
    conn = fake_conn([])
    env.create(conn, cfg, "PULSE_PR_7")
    env.drop(conn, "PULSE_PR_7")
    assert conn.executed == [
        "create database PULSE_PR_7 clone PULSE",
        "drop database if exists PULSE_PR_7",
    ]


def test_refresh_resumes_events_first_then_refreshes_all(cfg, fake_conn):
    conn = fake_conn([("show dynamic tables", show_rows("SUSPENDED"))])
    tables, seconds = env.refresh(conn, cfg, "PULSE_PR_7")
    assert [table["name"] for table in tables][0] == "EVENTS"
    resumes = [sql for sql in conn.executed if sql.endswith(" resume")]
    assert resumes[0] == "alter dynamic table PULSE_PR_7.MODEL.EVENTS resume"
    assert len(resumes) == 6
    assert conn.executed[-1].startswith("alter dynamic table PULSE_PR_7.MODEL.EVENTS, ")
    assert conn.executed[-1].endswith(" refresh")
    assert seconds >= 0


def test_check_passes_on_a_healthy_environment(cfg, fake_conn):
    masked = [{"REF_ENTITY_NAME": "PII", "REF_COLUMN_NAME": None, "POLICY_KIND": "MASKING_POLICY"}]
    guarded = [
        {"REF_ENTITY_NAME": name, "REF_COLUMN_NAME": None, "POLICY_KIND": "ROW_ACCESS_POLICY"}
        for name in ["EVENTS", "USERS", "ORGS", "DAILY_ACTIVITY"]
    ]
    conn = fake_conn(
        [
            ("show dynamic tables", show_rows()),
            ("from PULSE_PR_7.RAW.EVENTS", [{"N": 1000}]),
            ("count(distinct event_id)", [{"N": 990, "IDS": 990}]),
            ("MODEL.EVENTS', 'table'", [{"N": 3}]),
            ("MODEL.USERS', 'table'", [{"N": 2}]),
            ("MASK_PII", masked),
            ("COUNTRY_ACCESS", guarded),
            ("change_history", [{"N": 4}]),
        ]
    )
    results = env.check(conn, cfg, "PULSE_PR_7", TABLES)
    assert all(row["ok"] for row in results), env.format_results(results)
    assert len(results) == 9
    text = env.format_results(results)
    assert "ok   events deduplicated" in text
    assert "990 events from 1000 raw rows" in text


def test_check_flags_problems(cfg, fake_conn):
    conn = fake_conn(
        [
            ("show dynamic tables", show_rows()[:4]),
            ("from PULSE_PR_7.RAW.EVENTS", [{"N": 1000}]),
            ("count(distinct event_id)", [{"N": 1000, "IDS": 990}]),
            ("MODEL.EVENTS', 'table'", [{"N": 0}]),
            ("MODEL.USERS', 'table'", [{"N": 0}]),
            ("MASK_PII", []),
            ("COUNTRY_ACCESS", []),
            ("change_history", [{"N": 0}]),
        ]
    )
    results = env.check(conn, cfg, "PULSE_PR_7", TABLES)
    failed = {row["check"] for row in results if not row["ok"]}
    assert failed == {
        "dynamic tables present",
        "events deduplicated",
        "pii columns tagged",
        "masking policy on tag",
        "row access policy attached",
        "change history recorded",
    }
    assert "FAIL dynamic tables present" in env.format_results(results)
