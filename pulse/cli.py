import argparse
import json
import re
from pathlib import Path

import boto3

from pulse import config as config_module
from pulse import env, keys, ops, producer, snow

DYNAMIC_TABLE = re.compile(r"create\s+or\s+replace\s+dynamic\s+table\s+\w+\.(\w+)", re.IGNORECASE)


def expected_tables(migrations="migrations"):
    found = []
    for path in sorted(Path(migrations).glob("V*.sql")):
        found.extend(name.upper() for name in DYNAMIC_TABLE.findall(path.read_text()))
    if not found:
        raise SystemExit(f"no dynamic tables found under {migrations}, run from the repo root")
    return found


def emit(data, as_json, columns=None):
    if as_json:
        print(json.dumps(data, indent=2, default=str))
    elif isinstance(data, list):
        print(ops.table(data, columns or list(data[0].keys()) if data else []))
    else:
        width = max(len(key) for key in data)
        for key, value in data.items():
            print(f"{key.ljust(width)}  {value}")


def cmd_produce(args, config):
    if args.out:
        sink = producer.LocalSink(args.out)
    else:
        session = boto3.session.Session(region_name=config.aws.region)
        sink = producer.S3Sink(session.client("s3"), producer.bucket_name(config, session))
    producer.run(config, sink, files=args.files)


def cmd_env(args, config):
    name = env.env_name(config, pr=args.pr, name=args.name)
    conn = snow.connect(config, warehouse=config.snowflake.build_warehouse, query_tag="pulse-env")
    try:
        if args.action == "create":
            seconds = env.create(conn, config, name)
            print(f"created {name} as a clone of {config.snowflake.database} in {seconds}s")
        elif args.action == "drop":
            seconds = env.drop(conn, name)
            print(f"dropped {name} in {seconds}s")
        elif args.action == "refresh":
            tables, seconds = env.refresh(conn, config, name)
            print(ops.table(tables, ["name", "state", "target_lag", "refresh_mode"]))
            print(f"refreshed {len(tables)} dynamic tables in {seconds}s")
        else:
            results = env.check(conn, config, name, expected_tables())
            print(env.format_results(results))
            if not all(row["ok"] for row in results):
                raise SystemExit(1)
    finally:
        conn.close()


def cmd_keygen(args, config):
    private_path, public_path, body = keys.generate(args.out, args.name, args.force)
    print(f"private key {private_path}")
    print(f"public key {public_path}")
    print(f"one line public key for snowflake:\n{body}")


def cmd_ops(args, config):
    conn = snow.connect(config, query_tag="pulse-ops")
    try:
        if args.report == "latency":
            session = boto3.session.Session(region_name=config.aws.region)
            bucket = producer.bucket_name(config, session)
            hours = args.hours or config.ops.lookback_hours
            emit(ops.latency(conn, config, session.client("s3"), bucket, hours), args.json)
        elif args.report == "credits":
            emit(ops.credits(conn, config, args.days or config.ops.lookback_days), args.json)
        elif args.report == "warehouses":
            emit(ops.warehouses(conn, config, args.days or config.ops.lookback_days), args.json)
        else:
            emit(ops.tables(conn, config), args.json)
    finally:
        conn.close()


def build_parser():
    parser = argparse.ArgumentParser(prog="pulse")
    parser.add_argument("--config", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    produce = sub.add_parser("produce")
    produce.add_argument("--out", default=None)
    produce.add_argument("--files", type=int, default=None)
    produce.set_defaults(func=cmd_produce)

    environment = sub.add_parser("env")
    environment.add_argument("action", choices=["create", "drop", "check", "refresh"])
    environment.add_argument("--pr", type=int, default=None)
    environment.add_argument("--name", default=None)
    environment.set_defaults(func=cmd_env)

    keygen = sub.add_parser("keygen")
    keygen.add_argument("name")
    keygen.add_argument("--out", default="~/.pulse")
    keygen.add_argument("--force", action="store_true")
    keygen.set_defaults(func=cmd_keygen)

    reports = sub.add_parser("ops")
    reports.add_argument("report", choices=["latency", "credits", "warehouses", "tables"])
    reports.add_argument("--hours", type=int, default=None)
    reports.add_argument("--days", type=int, default=None)
    reports.add_argument("--json", action="store_true")
    reports.set_defaults(func=cmd_ops)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    config = config_module.load(args.config)
    args.func(args, config)


if __name__ == "__main__":
    main()
