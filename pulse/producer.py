import gzip
import io
import json
import time
from pathlib import Path

import boto3

from pulse.events import Simulation


def bucket_name(config, session=None):
    session = session or boto3.session.Session(region_name=config.aws.region)
    account = session.client("sts").get_caller_identity()["Account"]
    return f"{config.aws.bucket_prefix}-{account}"


def encode(events):
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as handle:
        for item in events:
            handle.write(json.dumps(item, separators=(",", ":")).encode())
            handle.write(b"\n")
    return buffer.getvalue()


class LocalSink:
    def __init__(self, root):
        self.root = Path(root)

    def put(self, key, body):
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)


class S3Sink:
    def __init__(self, client, bucket):
        self.client = client
        self.bucket = bucket

    def put(self, key, body):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentEncoding="gzip")


def run(config, sink, files=None, log=print):
    prod = config.producer
    sim = Simulation(
        prod.seed,
        prod.start_date,
        prod.days,
        prod.orgs,
        prod.duplicate_rate,
        prod.schema_v2_from_day,
    )
    started = time.monotonic()
    count = events = size = 0
    for key, batch in sim.files(prod.events_per_file, config.aws.events_prefix):
        if files is not None and count >= files:
            break
        body = encode(batch)
        sink.put(key, body)
        count += 1
        events += len(batch)
        size += len(body)
        if count % 10 == 0:
            log(f"{count} files, {events} events, {size / 1e6:.1f} MB gzipped")
    seconds = time.monotonic() - started
    summary = {"files": count, "events": events, "bytes": size, "seconds": round(seconds, 2)}
    log(json.dumps(summary))
    return summary
