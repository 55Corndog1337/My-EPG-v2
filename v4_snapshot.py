#!/usr/bin/env python3
"""Snapshot raw XMLTV sources for v4 mapping. Never export Xtream credentials."""
import gzip
import hashlib
import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

URLS = {
    "epg2": "https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg2.xml.gz",
    "epg6": "https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg6.xml.gz",
    "epg37": "https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg37.xml.gz",
}
OUT = Path("v4-snapshot")
OUT.mkdir(exist_ok=True)
manifest = {"generated_utc": datetime.now(timezone.utc).isoformat(), "sources": {}}
for source, url in URLS.items():
    request = urllib.request.Request(url, headers={"User-Agent": "My-EPG-v4-mapping-snapshot/1.0"})
    with urllib.request.urlopen(request, timeout=180) as response:
        raw = response.read(350 * 1024 * 1024 + 1)
    if len(raw) > 350 * 1024 * 1024:
        raise RuntimeError(source + " exceeds size limit")
    xml = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
    if not xml.lstrip().startswith((b"<?xml", b"<tv")):
        raise RuntimeError(source + " is not XMLTV")
    root = ET.fromstring(xml)
    if root.tag != "tv":
        raise RuntimeError(source + " unexpected root")
    channels = []
    for ch in root.findall("channel"):
        channels.append({"epg_id": ch.get("id", ""), "names": [n.text or "" for n in ch.findall("display-name")]})
    # Store the complete original XMLTV and a searchable channel index.
    (OUT / (source + ".xml.gz")).write_bytes(gzip.compress(xml, compresslevel=6))
    (OUT / (source + "-channels.json")).write_text(json.dumps(channels, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest["sources"][source] = {"url": url, "channels": len(channels),
        "programmes": len(root.findall("programme")),
        "sha256_xml": hashlib.sha256(xml).hexdigest()}
    print(source, "channels:", len(channels), "programmes:", len(root.findall("programme")))
manifest["xtream"] = {"encrypted_file": "xtream-channels-latest.enc.json",
    "note": "Live Xtream inventory is encrypted and never published in plaintext."}
(OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
