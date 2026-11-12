#!/usr/bin/env python3
"""Merge EPG 2, 6 and 37 into one XMLTV file, limited to US/UK/CA/VIP."""
import gzip
import io
import os
import re
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "v4-output" / "epg.xml.gz"
SOURCES = {
    "epg2": "https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg2.xml.gz",
    "epg6": "https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg6.xml.gz",
    "epg37": "https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg37.xml.gz",
}
# Require explicit country/category prefixes; never guess from programme titles.
GROUP = re.compile(r"^\\s*(?:US|USA|UK|CA|CANADA|VIP)\\s*(?:[-|:–—]\\s*|\\b)", re.I)

def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "My-EPG-combined/1.0"})
    with urllib.request.urlopen(req, timeout=180) as response:
        data = response.read()
    if data[:2] == b"\\x1f\\x8b":
        data = gzip.decompress(data)
    return data

def display_names(channel):
    return [(n.text or "").strip() for n in channel.findall("display-name")]

def main():
    merged = ET.Element("tv", {"generator-info-name": "Combined EPG 2+6+37"})
    all_channels = {}
    signatures = set()
    total = 0
    for source, url in SOURCES.items():
        data = download(url)
        tv = ET.fromstring(data)
        selected = {}
        for channel in tv.findall("channel"):
            cid = channel.get("id")
            if not cid or not any(GROUP.match(n) for n in display_names(channel)):
                continue
            # Identical IDs are shared; keep one channel entry, combine listings.
            selected[cid] = cid
            if cid not in all_channels:
                all_channels[cid] = channel
                merged.append(channel)
        count = 0
        for programme in tv.findall("programme"):
            cid = programme.get("channel")
            if cid not in selected:
                continue
            sig = (cid, programme.get("start"), programme.get("stop"),
                   programme.findtext("title", default=""))
            if sig in signatures:
                continue
            signatures.add(sig)
            merged.append(programme)
            count += 1
        print(f"{source}: {len(selected)} channels, {count} programmes", flush=True)
        total += count
    if not all_channels or not total:
        raise RuntimeError("No matching channels/programmes; existing guide preserved")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=OUT.parent, suffix=".tmp", delete=False) as f:
        tmp = Path(f.name)
    try:
        with gzip.open(tmp, "wb", compresslevel=6) as f:
            f.write(ET.tostring(merged, encoding="utf-8", xml_declaration=True))
        tmp.replace(OUT)
    finally:
        tmp.unlink(missing_ok=True)
    print(f"Published {len(all_channels)} unique channels and {total} programmes: {OUT}")

if __name__ == "__main__":
    main()
