from datetime import date
from pathlib import Path

import pytest

from pulse import config

ROOT = Path(__file__).resolve().parents[1]


def test_repo_config_loads():
    cfg = config.load(ROOT / "config.toml")
    assert cfg.snowflake.database == "PULSE"
    assert cfg.producer.start_date == date(2026, 9, 1)
    assert cfg.aws.events_prefix.endswith("/")
    assert cfg.snowflake.credit_price_usd > 0


def write(tmp_path, replace_from, replace_to):
    text = (ROOT / "config.toml").read_text().replace(replace_from, replace_to)
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


@pytest.mark.parametrize(
    "old, new, message",
    [
        ('database = "PULSE"', 'database = "pulse"', "upper case"),
        ('events_prefix = "events/"', 'events_prefix = "/events"', "events_prefix"),
        ("days = 14", "days = 0", "positive"),
        ("duplicate_rate = 0.005", "duplicate_rate = 0.5", "duplicate_rate"),
        ('start_date = "2026-09-01"', 'start_date = "yesterday"', "start_date"),
        ("schema_v2_from_day = 7", "schema_v2_from_day = 99", "schema_v2_from_day"),
        ("credit_price_usd = 3.0", "credit_price_usd = -1", "positive"),
        ('region = "us-east-2"', 'region = "mars"', "region"),
        ("lookback_hours = 24", "lookback_hours = 24\nextra = 1", "unknown keys"),
    ],
)
def test_bad_values_are_rejected(tmp_path, old, new, message):
    with pytest.raises(config.ConfigError, match=message):
        config.load(write(tmp_path, old, new))


def test_missing_section(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[aws]\nregion = "us-east-1"\nbucket_prefix = "pulse"\nevents_prefix = "e/"\n')
    with pytest.raises(config.ConfigError, match="snowflake"):
        config.load(path)


def test_env_var_points_at_config(tmp_path, monkeypatch):
    path = write(tmp_path, "orgs = 400", "orgs = 5")
    monkeypatch.setenv("PULSE_CONFIG", str(path))
    assert config.load().producer.orgs == 5
