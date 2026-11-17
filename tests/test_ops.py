import json
from datetime import UTC, datetime, timedelta

from pulse import ops


class FakeS3:
    def __init__(self, objects):
        self.objects = objects

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        start = int(ContinuationToken or 0)
        page = keys[start : start + 2]
        result = {"Contents": [{"Key": k, "LastModified": self.objects[k]} for k in page]}
        if start + 2 < len(keys):
            result["IsTruncated"] = True
            result["NextContinuationToken"] = str(start + 2)
        return result


def test_percentile_and_table():
    assert ops.percentile([], 0.5) is None
    assert ops.percentile([5, 1, 3], 0.5) == 3
    assert ops.percentile([5, 1, 3], 0.95) == 5
    text = ops.table([{"a": 1.23456, "b": None}, {"a": 1234.5, "b": "x"}], ["a", "b"])
    assert text.splitlines()[0].startswith("a")
    assert "1.2346" in text and "1234.5" in text
    assert ops.table([], ["a"]) == "(no rows)"


def test_latency_matches_files_and_pages_s3(cfg, fake_conn):
    put = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)
    objects = {
        f"events/dt=2026-09-01/part-0000{i}.ndjson.gz": put + timedelta(seconds=i) for i in range(5)
    }
    loads = [
        {
            "FILE_NAME": f"dt=2026-09-01/part-0000{i}.ndjson.gz",
            "PIPE_RECEIVED_TIME": put + timedelta(seconds=i + 5),
            "LAST_LOAD_TIME": put + timedelta(seconds=i + 40 + i * 10),
            "ROW_COUNT": 100,
            "ERROR_COUNT": 0,
            "STATUS": "Loaded",
        }
        for i in range(4)
    ]
    loads.append(
        {
            "FILE_NAME": "dt=2026-09-01/part-00004.ndjson.gz",
            "PIPE_RECEIVED_TIME": None,
            "LAST_LOAD_TIME": None,
            "ROW_COUNT": 0,
            "ERROR_COUNT": 3,
            "STATUS": "Load failed",
        }
    )
    status = json.dumps({"executionState": "RUNNING", "pendingFileCount": 0})
    conn = fake_conn([("copy_history", loads), ("pipe_status", [{"S": status}])])
    report = ops.latency(conn, cfg, FakeS3(objects), "pulse-events-1", 6)
    assert report["files_in_s3"] == 5
    assert report["files_loaded"] == 4
    assert report["files_failed"] == 1
    assert report["files_matched"] == 4
    assert report["rows_loaded"] == 400
    assert report["rows_with_errors"] == 3
    assert report["latency_p50_s"] == 60.0
    assert report["latency_max_s"] == 70.0
    assert report["pipe_state"] == "RUNNING"
    assert "start_time => dateadd(hour, -6" in conn.executed[0]


def test_credits_per_million_events(cfg, fake_conn):
    conn = fake_conn(
        [
            (
                "warehouse_metering_history",
                [
                    {
                        "WAREHOUSE_NAME": "PULSE_BUILD_WH",
                        "CREDITS": 0.5,
                        "COMPUTE": 0.45,
                        "CLOUD": 0.05,
                    },
                    {"WAREHOUSE_NAME": "PULSE_LOAD_WH", "CREDITS": 0.1, "COMPUTE": 0.1, "CLOUD": 0},
                ],
            ),
            (
                "pipe_usage_history",
                [{"PIPE_NAME": "EVENTS_PIPE", "CREDITS": "0.4", "BYTES": 20000000, "FILES": 40}],
            ),
            ("count(*)", [{"N": 500000}]),
        ]
    )
    report = ops.credits(conn, cfg, 7)
    assert report["total_credits"] == 1.0
    assert report["credits_per_million_events"] == 2.0
    assert report["usd_per_million_events"] == 6.0
    assert report["warehouse_credits"]["PULSE_BUILD_WH"] == 0.5
    assert report["pipe_files"] == 40
    assert "date_range_end => current_timestamp()" in conn.executed[0]


def test_warehouse_verdicts(cfg, fake_conn):
    conn = fake_conn(
        [
            (
                "show warehouses",
                [
                    {"NAME": "PULSE_LOAD_WH", "SIZE": "X-Small", "AUTO_SUSPEND": 60},
                    {"NAME": "PULSE_BUILD_WH", "SIZE": "X-Small", "AUTO_SUSPEND": 600},
                    {"NAME": "PULSE_QUERY_WH", "SIZE": "X-Small", "AUTO_SUSPEND": 60},
                    {"NAME": "COMPUTE_WH", "SIZE": "X-Small", "AUTO_SUSPEND": 600},
                ],
            ),
            (
                "warehouse_metering_history",
                [
                    {"WAREHOUSE_NAME": "PULSE_LOAD_WH", "CREDITS": 0.2},
                    {"WAREHOUSE_NAME": "PULSE_BUILD_WH", "CREDITS": 0.9},
                ],
            ),
            (
                "warehouse_load_history",
                [
                    {"WAREHOUSE_NAME": "PULSE_LOAD_WH", "RUNNING": 0.1, "QUEUED": 0.9},
                    {"WAREHOUSE_NAME": "PULSE_BUILD_WH", "RUNNING": 0.4, "QUEUED": 0.0},
                ],
            ),
            (
                "warehouse_name => 'PULSE_BUILD_WH'",
                [{"QUERIES": 12, "AVG_MS": 1234.5, "QUEUED_MS": 80.0, "SCANNED": 2500000000}],
            ),
        ]
    )
    report = ops.warehouses(conn, cfg, 7)
    by_name = {row["warehouse"]: row for row in report}
    assert set(by_name) == {"PULSE_LOAD_WH", "PULSE_BUILD_WH", "PULSE_QUERY_WH"}
    assert by_name["PULSE_LOAD_WH"]["verdict"] == "queueing, size up or add clusters"
    assert by_name["PULSE_BUILD_WH"]["verdict"] == "auto_suspend too long"
    assert by_name["PULSE_BUILD_WH"]["queries"] == 12
    assert by_name["PULSE_BUILD_WH"]["gb_scanned"] == 2.5
    assert by_name["PULSE_LOAD_WH"]["queries"] == 0
    assert by_name["PULSE_QUERY_WH"]["verdict"] == "unused in window"


def test_dynamic_table_report(cfg, fake_conn):
    conn = fake_conn(
        [
            (
                "show dynamic tables",
                [
                    {
                        "NAME": "EVENTS",
                        "SCHEDULING_STATE": "ACTIVE",
                        "TARGET_LAG": "DOWNSTREAM",
                        "REFRESH_MODE": "INCREMENTAL",
                    },
                    {
                        "NAME": "USERS",
                        "SCHEDULING_STATE": "ACTIVE",
                        "TARGET_LAG": "10 minutes",
                        "REFRESH_MODE": "INCREMENTAL",
                    },
                ],
            ),
            (
                "dynamic_table_refresh_history",
                [
                    {
                        "NAME": "EVENTS",
                        "STATE": "SUCCEEDED",
                        "REFRESH_ACTION": "INCREMENTAL",
                        "REFRESH_TRIGGER": "SCHEDULED",
                        "SECONDS": 4,
                        "INSERTED": 1000,
                        "DELETED": 0,
                    },
                    {
                        "NAME": "EVENTS",
                        "STATE": "SUCCEEDED",
                        "REFRESH_ACTION": "FULL",
                        "REFRESH_TRIGGER": "CREATION",
                        "SECONDS": 10,
                        "INSERTED": 50000,
                        "DELETED": 0,
                    },
                ],
            ),
        ]
    )
    report = ops.tables(conn, cfg)
    events = next(row for row in report if row["table"] == "EVENTS")
    assert events["refreshes_24h"] == 2
    assert events["incremental"] == 1
    assert events["avg_seconds"] == 7.0
    assert events["rows_inserted_24h"] == 51000
    users = next(row for row in report if row["table"] == "USERS")
    assert users["refreshes_24h"] == 0 and users["avg_seconds"] is None
