#!/usr/bin/env python3
"""Publish inspectable XMLTV shards without changing the full compressed guide."""
import gzip
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

OUT = Path("v4-output")
SHARDS = OUT / "readable"
MAX_BYTES = 24 * 1024 * 1024
ESPN_IDS = {f"{1705+n}.ESPN" for n in range(1, 601)}

def main():
    with gzip.open(OUT / "epg.xml.gz", "rb") as stream:
        root = ET.parse(stream).getroot()
    assert root.tag == "tv"
    channels = root.findall("channel")
    programmes = root.findall("programme")
    assert channels and programmes
    channel_by_id = {ch.get("id"): ch for ch in channels if ch.get("id")}
    SHARDS.mkdir(parents=True, exist_ok=True)
    # Remove obsolete shards, so the manifest always matches the current guide.
    for old in SHARDS.glob("part-*.xml"):
        old.unlink()

    manifest = []
    batch = []
    batch_bytes = 0
    index = 0

    def write_batch():
        nonlocal batch, batch_bytes, index
        if not batch:
            return
        index += 1
        ids = set(p.get("channel") for p in batch)
        part = ET.Element("tv", {"generator-info-name": "My-EPG-v2 readable shard"})
        for cid in sorted(ids):
            if cid in channel_by_id:
                part.append(channel_by_id[cid])
        part.extend(batch)
        name = f"part-{index:03d}.xml"
        target = SHARDS / name
        ET.ElementTree(part).write(target, encoding="utf-8", xml_declaration=True)
        size = target.stat().st_size
        assert size < 95_000_000, f"{name} exceeds GitHub limit"
        manifest.append({"file": f"readable/{name}", "channels": len(ids),
                         "programmes": len(batch), "bytes": size})
        batch = []
        batch_bytes = 0

    for p in programmes:
        size = len(ET.tostring(p, encoding="utf-8"))
        if batch and batch_bytes + size > MAX_BYTES:
            write_batch()
        batch.append(p)
        batch_bytes += size
    write_batch()

    diagnostic = ET.Element("tv", {"generator-info-name": "My-EPG-v2 ESPN+ diagnostics"})
    for ch in channels:
        if ch.get("id") in ESPN_IDS:
            diagnostic.append(ch)
    for p in programmes:
        if p.get("channel") in ESPN_IDS:
            diagnostic.append(p)
    assert len(diagnostic.findall("channel")) == 600
    assert len(diagnostic.findall("programme")) >= 600
    ET.ElementTree(diagnostic).write(OUT / "espn-plus.xml", encoding="utf-8", xml_declaration=True)
    assert (OUT / "espn-plus.xml").stat().st_size < 95_000_000

    signatures = Counter((p.get("channel"), p.get("start"), p.get("stop"),
                          p.findtext("title", default="")) for p in programmes)
    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "compressed_bytes": (OUT / "epg.xml.gz").stat().st_size,
        "uncompressed_xml_estimated_bytes": sum(len(ET.tostring(p, encoding="utf-8")) for p in programmes)
            + sum(len(ET.tostring(c, encoding="utf-8")) for c in channels),
        "channels": len(channels),
        "unique_channel_ids": len(channel_by_id),
        "programmes": len(programmes),
        "exact_duplicate_programmes": sum(count-1 for count in signatures.values() if count > 1),
        "espn_plus_channels": len(diagnostic.findall("channel")),
        "espn_plus_programmes": len(diagnostic.findall("programme")),
        "shards": manifest,
    }
    (OUT / "epg-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Readable XMLTV: {len(manifest)} parts, {len(channels)} channels, {len(programmes)} programmes", flush=True)

if __name__ == "__main__":
    main()
