"""The key generator runs without `cryptography`; TRACE must still accept its output.

`make init` runs on whatever Python the operator has, which may not have
`cryptography` installed — so the generator has a pure-Python path. If that
path produced subtly wrong PEM, anchoring would fail at first boot with a
confusing error. These tests close that loop by generating keys the slow way
and loading them the real way.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from app.anchoring.signing import Ed25519Signer, verify_tree_head

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "generate_signing_key.py"


@pytest.fixture(scope="module")
def generator():
    spec = importlib.util.spec_from_file_location("trace_keygen", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_has_no_dependencies_or_trace_imports() -> None:
    source = SCRIPT.read_text()
    assert "from app." not in source
    assert "import app" not in source


def test_pure_python_public_key_matches_the_reference_library(generator) -> None:
    """RFC 8032 §5.1.5 derivation, cross-checked 40 times."""
    import secrets

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    for _ in range(40):
        seed = secrets.token_bytes(32)
        expected = (
            Ed25519PrivateKey.from_private_bytes(seed)
            .public_key()
            .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        )
        assert generator.public_key_from_seed_pure(seed) == expected


def test_hand_built_pem_loads_in_the_reference_library(generator) -> None:
    """The fixed ASN.1 prefixes must produce genuinely valid PKCS8/SPKI."""
    import secrets

    from cryptography.hazmat.primitives import serialization

    seed = secrets.token_bytes(32)
    private_pem = generator.private_key_pem(seed)
    public_raw = generator.public_key_from_seed_pure(seed)

    loaded = serialization.load_pem_private_key(private_pem, password=None)
    assert loaded.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    ) == seed

    loaded_public = serialization.load_pem_public_key(generator.public_key_pem(public_raw))
    assert loaded_public.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ) == public_raw


def test_generated_key_is_usable_by_trace(tmp_path) -> None:
    """End to end: generate with the script, load with TRACE, sign, verify."""
    target = tmp_path / "keys" / "log.pem"
    result = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, str(SCRIPT), "--out", str(target)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert target.is_file()
    assert (target.stat().st_mode & 0o777) == 0o600

    signer = Ed25519Signer.from_pem_bytes(target.read_bytes())
    sth = signer.sign_tree_head(log_id="t:evidence", tree_size=3, root_hash="ab" * 32)
    assert verify_tree_head(sth, signer.public_key_raw)

    # The key id the script printed must be the one TRACE derives.
    printed = [line for line in result.stdout.splitlines() if "key id" in line][0]
    assert signer.key_id == printed.split(":")[1].strip()

    # And the published public key must match.
    public_line = [line for line in result.stdout.splitlines() if "public key" in line][0]
    assert base64.b64decode(public_line.split(":", 1)[1].strip()) == signer.public_key_raw
    assert hashlib.sha256(signer.public_key_raw).hexdigest()[:32] == signer.key_id


def test_script_refuses_to_overwrite_an_existing_key(tmp_path) -> None:
    target = tmp_path / "log.pem"
    first = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "--out", str(target)],
        capture_output=True, text=True, timeout=120,
    )
    assert first.returncode == 0
    original = target.read_bytes()

    second = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "--out", str(target)],
        capture_output=True, text=True, timeout=120,
    )
    assert second.returncode == 0
    assert "Refusing to overwrite" in second.stdout
    assert target.read_bytes() == original
