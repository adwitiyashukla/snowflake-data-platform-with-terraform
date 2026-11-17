from pathlib import Path

import pytest

from pulse import config

ROOT = Path(__file__).resolve().parents[1]


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.result = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append(sql)
        self.result = []
        for needle, rows in self.conn.answers:
            if needle.lower() in sql.lower():
                self.result = [dict(row) for row in rows]
                break
        self.rowcount = len(self.result)

    def fetchall(self):
        return self.result


class FakeConn:
    def __init__(self, answers):
        self.answers = answers
        self.executed = []
        self.closed = False

    def cursor(self, *args):
        return FakeCursor(self)

    def close(self):
        self.closed = True


@pytest.fixture
def cfg():
    return config.load(ROOT / "config.toml")


@pytest.fixture
def fake_conn():
    return FakeConn
