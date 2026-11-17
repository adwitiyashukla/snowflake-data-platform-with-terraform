import gzip
import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from pulse import config, producer

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def small(tmp_path):
    text = (ROOT / "config.toml").read_text()
    text = text.replace("orgs = 400", "orgs = 20").replace("days = 14", "days = 2")
    text = text.replace("events_per_file = 10000", "events_per_file = 300")
    text = text.replace("schema_v2_from_day = 7", "schema_v2_from_day = 1")
    path = tmp_path / "config.toml"
    path.write_text(text)
    return config.load(path)


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        yield


def test_encode_round_trips():
    events = [{"event_id": "a", "n": 1}, {"event_id": "b", "n": 2}]
    body = producer.encode(events)
    lines = gzip.decompress(body).decode().splitlines()
    assert [json.loads(line) for line in lines] == events
    assert producer.encode(events) == body


def test_local_sink_writes_files(small, tmp_path):
    sink = producer.LocalSink(tmp_path / "out")
    summary = producer.run(small, sink, log=lambda _: None)
    files = sorted((tmp_path / "out").rglob("*.ndjson.gz"))
    assert summary["files"] == len(files) > 0
    assert summary["events"] > 0
    with gzip.open(files[0], "rt") as handle:
        first = json.loads(handle.readline())
    assert first["event_type"] in ("org_created", "signup", "login")


def test_files_limit(small, tmp_path):
    sink = producer.LocalSink(tmp_path / "out")
    summary = producer.run(small, sink, files=2, log=lambda _: None)
    assert summary["files"] == 2


def test_s3_sink_uploads_gzip_objects(small, aws):
    session = boto3.session.Session(region_name="us-east-1")
    bucket = producer.bucket_name(small, session)
    assert bucket.startswith("pulse-events-") and bucket[-12:].isdigit()
    client = session.client("s3")
    client.create_bucket(Bucket=bucket)
    logs = []
    summary = producer.run(small, producer.S3Sink(client, bucket), files=5, log=logs.append)
    listed = client.list_objects_v2(Bucket=bucket, Prefix="events/")["Contents"]
    assert len(listed) == summary["files"] == 5
    assert sum(item["Size"] for item in listed) == summary["bytes"]
    first = client.get_object(Bucket=bucket, Key=listed[0]["Key"])
    assert first["ContentEncoding"] == "gzip"
    body = gzip.decompress(first["Body"].read()).decode().splitlines()
    assert all(json.loads(line)["event_id"] for line in body)
    assert json.loads(logs[-1])["files"] == 5
