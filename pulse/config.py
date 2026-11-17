import os
import re
import tomllib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

IDENT = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass
class Aws:
    region: str
    bucket_prefix: str
    events_prefix: str


@dataclass
class Snowflake:
    database: str
    raw_schema: str
    model_schema: str
    governance_schema: str
    raw_table: str
    pipe: str
    load_warehouse: str
    build_warehouse: str
    query_warehouse: str
    credit_price_usd: float


@dataclass
class Producer:
    seed: int
    start_date: date
    days: int
    orgs: int
    events_per_file: int
    duplicate_rate: float
    schema_v2_from_day: int


@dataclass
class Ops:
    lookback_hours: int
    lookback_days: int
    idle_auto_suspend_seconds: int
    queued_load_threshold: float


@dataclass
class Config:
    aws: Aws
    snowflake: Snowflake
    producer: Producer
    ops: Ops


class ConfigError(ValueError):
    pass


def _section(raw, name, keys):
    if name not in raw:
        raise ConfigError(f"missing section [{name}]")
    section = raw[name]
    missing = [k for k in keys if k not in section]
    if missing:
        raise ConfigError(f"[{name}] missing keys: {', '.join(missing)}")
    extra = [k for k in section if k not in keys]
    if extra:
        raise ConfigError(f"[{name}] unknown keys: {', '.join(extra)}")
    return section


def _positive(section, name, key, kinds=(int,)):
    value = section[key]
    if isinstance(value, bool) or not isinstance(value, kinds) or value <= 0:
        raise ConfigError(f"[{name}] {key} must be a positive number")
    return value


def _ident(section, name, key):
    value = section[key]
    if not isinstance(value, str) or not IDENT.match(value):
        raise ConfigError(f"[{name}] {key} must be an upper case snowflake identifier")
    return value


def load(path=None):
    path = Path(path or os.environ.get("PULSE_CONFIG", "config.toml"))
    with open(path, "rb") as handle:
        raw = tomllib.load(handle)

    aws = _section(raw, "aws", ["region", "bucket_prefix", "events_prefix"])
    if not re.match(r"^[a-z]{2}-[a-z]+-\d$", aws["region"]):
        raise ConfigError("[aws] region does not look like an aws region")
    if not re.match(r"^[a-z0-9][a-z0-9-]{2,40}$", aws["bucket_prefix"]):
        raise ConfigError("[aws] bucket_prefix must be a valid s3 bucket name prefix")
    if not aws["events_prefix"].endswith("/") or aws["events_prefix"].startswith("/"):
        raise ConfigError("[aws] events_prefix must end with / and not start with /")

    sf = _section(
        raw,
        "snowflake",
        [
            "database",
            "raw_schema",
            "model_schema",
            "governance_schema",
            "raw_table",
            "pipe",
            "load_warehouse",
            "build_warehouse",
            "query_warehouse",
            "credit_price_usd",
        ],
    )
    for key in sf:
        if key != "credit_price_usd":
            _ident(sf, "snowflake", key)
    _positive(sf, "snowflake", "credit_price_usd", (int, float))

    prod = _section(
        raw,
        "producer",
        [
            "seed",
            "start_date",
            "days",
            "orgs",
            "events_per_file",
            "duplicate_rate",
            "schema_v2_from_day",
        ],
    )
    if not isinstance(prod["seed"], int) or isinstance(prod["seed"], bool):
        raise ConfigError("[producer] seed must be an integer")
    start = prod["start_date"]
    if isinstance(start, str):
        try:
            start = date.fromisoformat(start)
        except ValueError as error:
            raise ConfigError("[producer] start_date must look like 2026-09-01") from error
    if isinstance(start, datetime) or not isinstance(start, date):
        raise ConfigError("[producer] start_date must be a date like 2026-09-01")
    prod["start_date"] = start
    for key in ["days", "orgs", "events_per_file"]:
        _positive(prod, "producer", key)
    if not 0 <= prod["duplicate_rate"] < 0.2:
        raise ConfigError("[producer] duplicate_rate must be between 0 and 0.2")
    if not 0 <= prod["schema_v2_from_day"] <= prod["days"]:
        raise ConfigError("[producer] schema_v2_from_day must be between 0 and days")

    ops = _section(
        raw,
        "ops",
        ["lookback_hours", "lookback_days", "idle_auto_suspend_seconds", "queued_load_threshold"],
    )
    for key in ["lookback_hours", "lookback_days", "idle_auto_suspend_seconds"]:
        _positive(ops, "ops", key)
    _positive(ops, "ops", "queued_load_threshold", (int, float))

    return Config(
        aws=Aws(**aws),
        snowflake=Snowflake(**sf),
        producer=Producer(**prod),
        ops=Ops(**ops),
    )
