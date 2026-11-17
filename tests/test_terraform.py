import re
from pathlib import Path

import hcl2
import pytest

from pulse import config

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT / "terraform" / "platform"
STATE = ROOT / "terraform" / "state"
PREVIEW_RESOURCES = {"snowflake_table", "snowflake_pipe"}


def clean(value):
    if isinstance(value, dict):
        return {clean(k): clean(v) for k, v in value.items() if k != "__is_block__"}
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, str) and len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def parse(folder):
    parsed = {}
    for path in sorted(folder.glob("*.tf")):
        with open(path) as handle:
            parsed[path.name] = clean(hcl2.load(handle))
    return parsed


def text(folder):
    return "\n".join(path.read_text() for path in sorted(folder.glob("*.tf")))


def declared(parsed, block):
    names = set()
    for document in parsed.values():
        for item in document.get(block, []):
            names.update(item.keys())
    return names


def declared_resources(parsed, block="resource"):
    found = set()
    for document in parsed.values():
        for item in document.get(block, []):
            for kind, named in item.items():
                for name in named:
                    found.add(f"{kind}.{name}")
    return found


@pytest.fixture(scope="module")
def platform():
    return parse(PLATFORM), text(PLATFORM)


@pytest.fixture(scope="module")
def cfg():
    return config.load(ROOT / "config.toml")


def test_state_root_parses_and_is_self_contained():
    parsed = parse(STATE)
    variables = declared(parsed, "variable")
    used = set(re.findall(r"\bvar\.(\w+)", text(STATE)))
    assert used == variables
    assert "aws_s3_bucket.state" in declared_resources(parsed)


def test_every_variable_is_declared_and_used(platform):
    parsed, body = platform
    variables = declared(parsed, "variable")
    used = set(re.findall(r"\bvar\.(\w+)", body))
    assert used - variables == set()
    assert variables - used == set()


def test_every_local_is_defined_and_used(platform):
    parsed, body = platform
    defined = set()
    for document in parsed.values():
        for block in document.get("locals", []):
            defined.update(block.keys())
    used = set(re.findall(r"\blocal\.(\w+)", body))
    assert used - defined == set()
    assert defined - used == set()


def test_resource_references_resolve(platform):
    parsed, body = platform
    resources = declared_resources(parsed)
    data = declared_resources(parsed, "data")
    for kind, name in re.findall(r"(?<!data\.)\b((?:aws|snowflake)_\w+)\.(\w+)\b", body):
        if kind.endswith("_resource"):
            continue
        assert f"{kind}.{name}" in resources, f"{kind}.{name} is referenced but not declared"
    for kind, name in re.findall(r"\bdata\.(\w+)\.(\w+)\b", body):
        assert f"{kind}.{name}" in data


def test_preview_features_cover_the_preview_resources_used(platform):
    parsed, body = platform
    used_types = {address.split(".")[0] for address in declared_resources(parsed)}
    enabled = set(re.findall(r'"(snowflake_\w+_resource)"', body))
    for kind in used_types & PREVIEW_RESOURCES:
        assert f"{kind}_resource" in enabled
    assert enabled == {f"{kind}_resource" for kind in used_types & PREVIEW_RESOURCES}


def test_providers_are_pinned(platform):
    parsed, _ = platform
    providers = parsed["providers.tf"]["terraform"][0]["required_providers"][0]
    assert providers["aws"]["version"].startswith("~> 6.")
    assert providers["snowflake"]["version"].startswith("~> 2.")
    assert providers["snowflake"]["source"] == "snowflakedb/snowflake"
    assert parsed["providers.tf"]["terraform"][0]["backend"][0]["s3"]["use_lockfile"] is True


def test_terraform_defaults_match_config(platform, cfg):
    parsed, body = platform
    defaults = {}
    for document in parsed.values():
        for item in document.get("variable", []):
            for name, spec in item.items():
                if "default" in spec:
                    defaults[name] = spec["default"]
    assert defaults["database"] == cfg.snowflake.database
    assert defaults["bucket_prefix"] == cfg.aws.bucket_prefix
    assert defaults["events_prefix"] == cfg.aws.events_prefix
    assert defaults["aws_region"] == cfg.aws.region
    warehouses = set(re.findall(r"^    (LOAD|BUILD|QUERY) += ", body, re.M))
    assert warehouses == {"LOAD", "BUILD", "QUERY"}
    assert cfg.snowflake.load_warehouse == f"{cfg.snowflake.database}_LOAD_WH"
    assert cfg.snowflake.build_warehouse == f"{cfg.snowflake.database}_BUILD_WH"
    assert cfg.snowflake.query_warehouse == f"{cfg.snowflake.database}_QUERY_WH"
    assert '"${var.database}_${each.key}_WH"' in body
    assert f'name        = "{cfg.snowflake.pipe}"' in body
    assert f'name                        = "{cfg.snowflake.raw_table}"' in body
    schemas = set(re.findall(r"^    (RAW|MODEL|GOVERNANCE|SCHEMACHANGE) += ", body, re.M))
    wanted = {cfg.snowflake.raw_schema, cfg.snowflake.model_schema, cfg.snowflake.governance_schema}
    assert wanted <= schemas


def test_migrations_use_names_terraform_creates(platform, cfg):
    parsed, body = platform
    sql = "\n".join(path.read_text() for path in sorted((ROOT / "migrations").glob("*.sql")))
    for warehouse in set(re.findall(r"^warehouse = (\w+)$", sql, re.M)):
        assert warehouse.upper() == cfg.snowflake.build_warehouse
    functional = set(re.findall(r"^    (\w+) += \"", body.split("functional_roles")[1], re.M))
    for role in set(re.findall(r"'PULSE_([A-Z_]+)'", sql)):
        assert role in functional, f"{role} is used in sql but terraform does not create it"
    assert "PULSE_PII_READER" in sql and "PULSE_ANALYST_EU" in sql


def test_landing_table_matches_the_pipe_and_model(platform):
    parsed, body = platform
    columns = re.findall(r'column \{\n    name += "(\w+)"', body)
    assert columns == ["RECORD", "FILE_NAME", "FILE_ROW_NUMBER", "LOADED_AT"]
    assert "(RECORD, FILE_NAME, FILE_ROW_NUMBER)" in body
    assert "change_tracking             = true" in body
    events_sql = (ROOT / "migrations" / "V1.1.0__events.sql").read_text()
    for column in ["record", "file_name", "file_row_number", "loaded_at"]:
        assert column in events_sql
