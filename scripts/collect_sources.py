#!/usr/bin/env python3
"""Prepare fresh private Xtream inventory and XMLTV source files in one Actions job.

Private provider inventory is never uploaded as an artifact or committed.
Public EPG source snapshots contain only upstream public XMLTV data.
"""
import csv
import gzip
import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_epg

def main():
    # Fail closed: no stale CSV fallback when the authenticated provider is unavailable.
    for name in ("XTREAM_URL", "XTREAM_USERNAME", "XTREAM_PASSWORD"):
        if not os.environ.get(name):
            raise RuntimeError("Missing required GitHub Actions secret: " + name)
    catalog = build_epg.refresh_playlist_catalog()
    if not catalog:
        raise RuntimeError("Xtream returned no allowed US/UK/CA channels")
    private = Path("private")
    private.mkdir(exist_ok=True)
    with (private / "channels.csv").open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=["Source","Group","ChannelName","StreamID","EPGID","TVGName","ProviderID","Scope"])
        writer.writeheader()
        writer.writerows(catalog)
    print("Xtream catalog collected privately:", len(catalog), "channels")

    source_dir = Path("sources")
    source_dir.mkdir(exist_ok=True)
    summary = {"generated_at": datetime.now(timezone.utc).isoformat(), "sources": {}}
    for name, url in build_epg.SOURCES.items():
        raw = build_epg.download(url)
        root = ET.fromstring(raw)
        if root.tag != "tv":
            raise RuntimeError(name + " returned invalid XMLTV")
        channel_count = len(root.findall("channel"))
        programme_count = len(root.findall("programme"))
        if not channel_count or not programme_count:
            raise RuntimeError(name + " has no channels or programmes")
        with gzip.open(source_dir / (name + ".xml.gz"), "wb", compresslevel=6) as out:
            out.write(raw)
        summary["sources"][name] = {"channels": channel_count, "programmes": programme_count}
        print(name, "validated:", channel_count, "channels;", programme_count, "programmes")
    Path("sources/summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("Validated EPG source snapshots ready for the initial combined guide build")

if __name__ == "__main__":
    main()
