import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def generate(folder, name, force=False):
    folder = Path(folder).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    private_path = folder / f"{name}.p8"
    public_path = folder / f"{name}.pub"
    if private_path.exists() and not force:
        raise SystemExit(f"{private_path} exists, pass --force to replace it")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_path.write_bytes(private_pem)
    os.chmod(private_path, 0o600)
    public_path.write_bytes(public_pem)
    return private_path, public_path, one_line(public_pem.decode())


def one_line(public_pem):
    return "".join(line for line in public_pem.splitlines() if not line.startswith("-----"))
