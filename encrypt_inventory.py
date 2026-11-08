#!/usr/bin/env python3
"""Encrypt the latest Xtream inventory; never publish plaintext."""
import base64
import json
import os
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

source = Path("reports/xtream-channels-latest.csv")
status = Path("reports/xtream-inventory-status.txt")
password = os.environ.get("XTREAM_EXPORT_PASSWORD", "")
if not password:
    raise SystemExit("XTREAM_EXPORT_PASSWORD secret is not configured")
if not source.is_file() or not status.is_file():
    raise SystemExit("Latest inventory missing; refusing to export")
if "Source: live_xtream" not in status.read_text(encoding="utf-8"):
    raise SystemExit("Latest inventory was fallback, not a live Xtream pull; refusing to export")
salt = os.urandom(16)
nonce = os.urandom(12)
key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode("utf-8"))
plaintext = source.read_bytes()
ciphertext = AESGCM(key).encrypt(nonce, plaintext, b"my-epg-v2-xtream-inventory-v1")
out = Path("encrypted-export")
out.mkdir(exist_ok=True)
(out / "xtream-channels-latest.enc.json").write_text(json.dumps({
    "format": "my-epg-v2-xtream-inventory-v1",
    "cipher": "AES-256-GCM",
    "kdf": "scrypt",
    "scrypt_n": 32768,
    "scrypt_r": 8,
    "scrypt_p": 1,
    "salt_b64": base64.b64encode(salt).decode(),
    "nonce_b64": base64.b64encode(nonce).decode(),
    "ciphertext_b64": base64.b64encode(ciphertext).decode()
}, separators=(",", ":")) + "\n", encoding="utf-8")
print("Encrypted Xtream inventory export created; plaintext not uploaded.")
