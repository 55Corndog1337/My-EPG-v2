
import gzip
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

EPG = Path("v4-output/epg.xml.gz")

def main():
    if not EPG.exists():
        sys.exit(f"Missing guide: {EPG}")

    with gzip.open(EPG, "rb") as f:
        tree = ET.parse(f)

    root = tree.getroot()
    channels = root.findall("channel")
    programmes = root.findall("programme")

    # Verified ESPN+ 01-50 mappings.
    # Do not guess IDs for 51-100.
    mapping = {
        f"v4.{234276 + n}": f"ESPNPlus.{n}"
        for n in range(1, 51)
    }

    existing = {
        ch.get("id") for ch in channels
    }

    for old, new in mapping.items():
        if old not in existing:
            sys.exit(f"Missing source ID: {old}")
        if new in existing:
            sys.exit(f"Duplicate target ID: {new}")

    channel_count = 0
    programme_count = 0

    for ch in channels:
        old = ch.get("id")
        if old in mapping:
            ch.set("id", mapping[old])
            channel_count += 1

    for programme in programmes:
        old = programme.get("channel")
        if old in mapping:
            programme.set("channel", mapping[old])
            programme_count += 1

    if channel_count != len(mapping):
        sys.exit("Channel validation failed")

    valid_ids = {
        ch.get("id") for ch in channels
    }

    if any(
        p.get("channel") not in valid_ids
        for p in programmes
    ):
        sys.exit("Orphan programme detected")

    temporary = EPG.with_suffix(".tmp")

    with gzip.open(temporary, "wb") as f:
        tree.write(
            f,
            encoding="utf-8",
            xml_declaration=True
        )

    temporary.replace(EPG)

    print(
        f"Updated {channel_count} ESPN+ IDs "
        f"and {programme_count} programmes"
    )

if __name__ == "__main__":
    main()
