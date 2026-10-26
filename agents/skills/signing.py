"""ed25519 detached signatures — authenticity layer of the trust model.

A publisher signs the manifest's author fields with an ed25519 private key;
verification checks the signature against that publisher's trusted public key
in ``~/.prometheus/publishers.json`` (managed by ``skill trust``). Enforced at
install for remote sources (git / registry); ``--no-verify`` is the explicit
local-dev escape hatch.

The ``trusted`` flag and scan/install-time fields (``path``, ``root``) are
**excluded** from the signed payload — otherwise setting ``trusted`` / relocating
an installed skill would invalidate its signature.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# cryptography is only imported on first use — signing is off the hot path and
# keeping the import lazy means a missing/incompatible wheel cannot break a
# registry scan (manifests-only) on import.
def _crypto():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    return ed25519, serialization


def generate_keypair() -> tuple[bytes, bytes]:
    """Return ``(private_pem, public_pem)`` for a new publisher identity."""
    ed25519, serialization = _crypto()
    priv = ed25519.Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv_pem, pub_pem


def _parse_private(pem: bytes):
    ed25519, serialization = _crypto()
    return serialization.load_pem_private_key(pem, password=None)


def _parse_public(pem: str | bytes):
    ed25519, serialization = _crypto()
    return serialization.load_pem_public_key(pem.encode() if isinstance(pem, str) else pem)


def canonical_signature_payload(data: dict[str, Any]) -> bytes:
    """Stable canonical bytes over a dict (sorted keys — hash-independent)."""
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_manifest(manifest, private_pem: bytes) -> str:
    """Sign a manifest's author fields; return hex signature."""
    from agents.skills.manifest import SkillManifest

    payload = _author_fields(manifest)
    priv = _parse_private(private_pem)
    return priv.sign(canonical_signature_payload(payload)).hex()


def verify_manifest(manifest, public_pem: str | bytes) -> bool:
    """Verify a manifest's signature against ``public_pem``."""
    if not manifest.signature:
        return False
    try:
        pub = _parse_public(public_pem)
        pub.verify(
            bytes.fromhex(manifest.signature), canonical_signature_payload(_author_fields(manifest))
        )
        return True
    except Exception:
        return False


def _author_fields(manifest) -> dict[str, Any]:
    """The manifest fields a signature actually covers (no transient fields)."""
    return manifest.model_dump(exclude={"signature", "trusted", "path", "root", "instruction_body"})


# ── Publisher key store (~/.prometheus/publishers.json) ────────────────


def publishers_path() -> Path:
    return Path.home() / ".prometheus" / "publishers.json"


def load_publishers(path: Path | None = None) -> dict[str, str]:
    store = {}
    p = path or publishers_path()
    if p.is_file():
        try:
            store = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            store = {}
    if not isinstance(store, dict):
        return {}
    return {str(k): str(v) for k, v in store.items()}


def save_publishers(store: dict[str, str], path: Path | None = None) -> None:
    p = path or publishers_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(store, indent=2, sort_keys=True), encoding="utf-8")


def add_publisher(publisher: str, public_key_pem: str | bytes, path: Path | None = None) -> None:
    store = load_publishers(path)
    store[publisher] = (
        public_key_pem.decode() if isinstance(public_key_pem, bytes) else public_key_pem
    )
    save_publishers(store, path)


def is_trusted_publisher(publisher: str, path: Path | None = None) -> bool:
    return publisher in load_publishers(path)


def verify_manifest_signature(manifest, path: Path | None = None) -> tuple[bool, str]:
    """Verify a manifest's signature against its declared trusted publisher.

    Returns ``(ok, reason)``: ``ok=False`` with the precise reason when the
    publisher is undeclared, untrusted, unsigned, or the signature is bad —
    so the install gate can report exactly which check failed.
    """
    if not manifest.publisher:
        return False, "manifest declares no publisher"
    if not manifest.signature:
        return False, "manifest carries no signature"
    pem = load_publishers(path).get(manifest.publisher)
    if pem is None:
        return (
            False,
            f"publisher {manifest.publisher!r} is not trusted (run: skill trust {manifest.publisher})",
        )
    if not verify_manifest(manifest, pem):
        return False, "signature verification failed"
    return True, "signature verified"
