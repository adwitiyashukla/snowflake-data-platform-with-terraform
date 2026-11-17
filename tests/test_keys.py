from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization

from pulse import keys
from pulse.cli import main


def test_generate_writes_pkcs8_pair(tmp_path):
    private_path, public_path, body = keys.generate(tmp_path / "keys", "deployer")
    assert private_path.read_text().startswith("-----BEGIN PRIVATE KEY-----")
    assert public_path.read_text().startswith("-----BEGIN PUBLIC KEY-----")
    assert "-----" not in body and "\n" not in body
    private = serialization.load_pem_private_key(private_path.read_bytes(), password=None)
    assert private.key_size == 2048
    assert keys.one_line(public_path.read_text()) == body
    with pytest.raises(SystemExit):
        keys.generate(tmp_path / "keys", "deployer")
    keys.generate(tmp_path / "keys", "deployer", force=True)


def test_keygen_command(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "config.toml").write_text((root / "config.toml").read_text())
    main(["keygen", "ops", "--out", str(tmp_path / "k")])
    out = capsys.readouterr().out
    assert "one line public key" in out
    assert (tmp_path / "k" / "ops.p8").exists()
