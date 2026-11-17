import collections
import json
from datetime import date

from pulse.events import PLAN_ORDER, PLAN_PRICE, Simulation, weighted


def run(seed=1, days=3, orgs=30, duplicate_rate=0.01, v2_from=1, per_file=400):
    sim = Simulation(seed, date(2026, 9, 1), days, orgs, duplicate_rate, v2_from)
    files = list(sim.files(per_file, "events/"))
    return sim, files, [item for _, batch in files for item in batch]


def test_same_seed_same_events():
    _, _, first = run()
    _, _, second = run()
    assert [item["event_id"] for item in first] == [item["event_id"] for item in second]
    assert json.dumps(first[:50]) == json.dumps(second[:50])


def test_different_seed_different_events():
    _, _, first = run(seed=1)
    _, _, second = run(seed=2)
    assert first[0]["event_id"] != second[0]["event_id"]


def test_file_layout_and_sizes():
    _, files, events = run(per_file=400)
    keys = [key for key, _ in files]
    assert keys == sorted(keys)
    assert all(key.startswith("events/dt=2026-09-0") and key.endswith(".ndjson.gz") for key in keys)
    assert all(len(batch) <= 400 for _, batch in files)
    assert sum(len(batch) for _, batch in files) == len(events)
    assert len(events) > 1000


def test_event_shape():
    _, _, events = run()
    keys = {
        "event_id",
        "event_type",
        "event_ts",
        "schema_version",
        "org_id",
        "user_id",
        "session_id",
        "properties",
        "context",
        "user",
    }
    for item in events[:500]:
        assert set(item) == keys
        assert item["event_ts"].endswith("Z") and len(item["event_ts"]) == 24
        assert item["context"]["country"]
        if item["user_id"]:
            assert "@" in item["user"]["email"]
            assert item["context"]["ip"].count(".") == 3
        else:
            assert item["user"] is None


def test_schema_version_switches_on_the_configured_day():
    _, _, events = run(days=4, v2_from=2)
    by_version = collections.defaultdict(set)
    for item in events:
        by_version[item["schema_version"]].add(item["event_ts"][:10])
    assert "2026-09-01" in by_version[1]
    assert "2026-09-04" in by_version[2]
    assert all("locale" in item["context"] for item in events if item["schema_version"] == 2)
    assert all("locale" not in item["context"] for item in events if item["schema_version"] == 1)


def test_duplicates_arrive_late_and_match_original():
    _, _, events = run(days=4, duplicate_rate=0.05)
    counts = collections.Counter(item["event_id"] for item in events)
    dupes = [event_id for event_id, n in counts.items() if n > 1]
    assert 0 < len(dupes) < len(counts) * 0.1
    originals = {}
    for item in events:
        if item["event_id"] in dupes:
            if item["event_id"] in originals:
                assert originals[item["event_id"]] == item
            originals[item["event_id"]] = item


def test_no_duplicates_when_rate_is_zero():
    _, _, events = run(duplicate_rate=0)
    assert len({item["event_id"] for item in events}) == len(events)


def test_plans_and_payments_are_consistent():
    sim, _, events = run(days=10, orgs=120)
    for item in events:
        if item["event_type"].startswith("payment"):
            assert item["properties"]["amount_cents"] == PLAN_PRICE[item["properties"]["plan"]]
            assert item["properties"]["plan"] != "free"
        if item["event_type"].startswith("subscription"):
            assert item["properties"]["plan"] in PLAN_ORDER
    for org in sim.orgs:
        assert org["plan"] in PLAN_ORDER


def test_weighted_respects_weights():
    import random

    rng = random.Random(0)
    picks = collections.Counter(weighted(rng, [("a", 90), ("b", 10)]) for _ in range(2000))
    assert picks["a"] > picks["b"] * 5
