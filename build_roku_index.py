#!/usr/bin/env python3
"""Build small, independent Roku guide files from the existing combined XMLTV.gz.
No playlist URLs, stream URLs or credentials are needed or published.
The Roku app uses a deterministic 128-way ASCII ID lookup.
"""
import argparse
import gzip
import json
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

def normalize(value):
    return (value or "").strip().lower()

def bucket(channel_id):
    # Match Asc(Mid(...)) hashing in IndexedGuideTask.brs, for ASCII IDs.
    return sum(ord(ch) for ch in normalize(channel_id)) % 128

def epg_time(value):
    match = re.match(r"^(\d{14})(?:\s*([+-])(\d\d)(\d\d))?", value or "")
    if not match:
        return None
    dt = datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    if match.group(2):
        minutes = (int(match.group(3))*60 + int(match.group(4))) * (1 if match.group(2)=="+" else -1)
        dt -= timedelta(minutes=minutes)
    return int(dt.timestamp())


# Exact, previously reviewed mappings already committed in matches.csv.
# Use the original EPG37/EPG2 programme source to recover listings omitted
# from the combined v5 XMLTV. Never invent programming or copy stream URLs.
def recover_mapped_listings(shows, now):
    import csv
    import urllib.request
    from collections import Counter
    mapping_file = Path("matches.csv")
    if not mapping_file.exists():
        print("Roku recovery: matches.csv unavailable")
        return {"source_matched": 0, "aliases_added": 0}
    sources = {
        "epg37": "https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg37.xml.gz",
        "epg2": "https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg2.xml.gz",
        "epg6": "https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg6.xml.gz",
    }
    def namekey(value):
        return "name:" + re.sub(r"[^a-z0-9]", "", (value or "").lower())
    pair_aliases = defaultdict(set)
    alias_owners = defaultdict(set)
    with mapping_file.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            source_field = (row.get("source") or "").lower()
            src = next((key for key in sources if key in source_field), "")
            source_id = (row.get("source_channel_id") or "").strip()
            if not src or not source_id:
                continue
            pair = (src, source_id)
            options = [(row.get("original_tvg_id") or "").strip().lower(),
                       (row.get("output_tvg_id") or "").strip().lower(),
                       namekey(row.get("playlist_channel"))]
            for alias in options:
                if alias and alias != "name:" and all(ord(ch) < 128 for ch in alias):
                    pair_aliases[pair].add(alias)
                    alias_owners[alias].add(pair)
    # Don't assign one programme feed to an ambiguous playlist identifier.
    targets = {pair: {alias for alias in aliases if len(alias_owners[alias]) == 1}
               for pair, aliases in pair_aliases.items()}
    by_source = defaultdict(set)
    for src, source_id in targets:
        by_source[src].add(source_id)
    recovered = {}
    end = now + 24 * 3600
    for src, wanted in by_source.items():
        if not wanted:
            continue
        try:
            request = urllib.request.Request(
                sources[src], headers={"User-Agent": "My-EPG-Roku-Index/1.0"})
            with urllib.request.urlopen(request, timeout=120) as response:
                with gzip.GzipFile(fileobj=response) as stream:
                    events = ET.iterparse(stream, events=("start", "end"))
                    _, root = next(events)
                    for event, elem in events:
                        if event != "end":
                            continue
                        if elem.tag.rsplit("}", 1)[-1] == "programme":
                            cid = elem.get("channel") or ""
                            if cid in wanted:
                                start = epg_time(elem.get("start"))
                                stop = epg_time(elem.get("stop"))
                                if start is not None and start < end and (stop is None or stop > now):
                                    title = next(((child.text or "").strip() for child in elem
                                                  if child.tag.rsplit("}", 1)[-1] == "title"), "")
                                    if title:
                                        recovered.setdefault((src, cid), []).append({
                                            "start": start, "stop": stop or start + 3600,
                                            "title": title[:160]})
                            elem.clear()
                            root.clear()
            print(f"Roku recovery: {src}: {sum((src,cid) in recovered for cid in wanted)} IDs with programmes")
        except Exception as exc:
            print(f"WARNING: Roku recovery {src} unavailable: {type(exc).__name__}")
    added = 0
    for pair, options in targets.items():
        items = recovered.get(pair, [])
        if not items:
            continue
        items.sort(key=lambda item: item["start"])
        for alias in options:
            if not shows.get(alias):
                shows[alias] = items[:12]
                added += 1
    return {"source_matched": len(recovered), "aliases_added": added}


def recover_local_stations(shows, now):
    """Optional exact call-sign rescue from regional XMLTV guides (no fuzzy network matching)."""
    import csv
    import urllib.request
    from collections import defaultdict
    mapping = Path("matches.csv")
    if not mapping.exists():
        return 0
    wanted = defaultdict(set)
    with mapping.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            label = (row.get("playlist_channel") or "").strip()
            match = re.search(r"\(([WK][A-Z]{2,5})(?:-DT1?)?\)\s*$", label, re.I)
            if not match:
                continue
            code = match.group(1).upper()
            key = "name:" + re.sub(r"[^a-z0-9]", "", label.lower())
            original = (row.get("original_tvg_id") or "").strip().lower()
            wanted[code].add(key)
            if original and all(ord(c) < 128 for c in original):
                wanted[code].add(original)
    recovered = defaultdict(list)
    for region in ("us-tn", "us-va"):
        url = "https://iptv-org.github.io/epg/guides/" + region + "/tvtv.us.epg.xml"
        try:
            request = urllib.request.Request(url, headers={"User-Agent":"My-EPG-Roku-Index/1.0"})
            with urllib.request.urlopen(request, timeout=100) as response:
                events = ET.iterparse(response, events=("start", "end"))
                _, root = next(events)
                for event, elem in events:
                    if event != "end":
                        continue
                    if elem.tag.rsplit("}", 1)[-1] == "programme":
                        source_id = (elem.get("channel") or "").upper()
                        match = re.match(r"^([WK][A-Z]{2,5})(?:-(?:DT1?|TV))?(?:\.|$)", source_id)
                        if match:
                            code = match.group(1)
                            if code in wanted:
                                start = epg_time(elem.get("start"))
                                stop = epg_time(elem.get("stop"))
                                if start is not None and start < now+24*3600 and (stop is None or stop>now):
                                    title = next(((x.text or "").strip() for x in elem
                                                  if x.tag.rsplit("}",1)[-1] == "title"), "")
                                    if title:
                                        recovered[code].append({"start":start,"stop":stop or start+3600,"title":title[:160]})
                        elem.clear()
                        root.clear()
            print(f"Roku local recovery: {region} read successfully")
        except Exception as exc:
            print(f"WARNING: Roku local guide {region} unavailable: {type(exc).__name__}")
    count = 0
    for code, aliases in wanted.items():
        items = recovered.get(code, [])
        if not items:
            continue
        items.sort(key=lambda x:x["start"])
        for alias in aliases:
            if not shows.get(alias):
                shows[alias] = items[:12]
                count += 1
    print(f"Roku local station aliases restored: {count}")
    return count

def build(source, destination):
    now = int(datetime.now(timezone.utc).timestamp())
    shows = defaultdict(list)
    source_ids = set()
    total_programmes = 0
    in_window_programmes = 0
    source = Path(source)
    with (gzip.open(source,"rb") if source.suffix==".gz" else source.open("rb")) as fh:
        events=ET.iterparse(fh,events=("start","end"))
        _,root=next(events)
        for event,elem in events:
            if event!="end":
                continue
            if elem.tag.rsplit("}",1)[-1]=="programme":
                cid=normalize(elem.get("channel"))
                if cid:
                    source_ids.add(cid)
                    total_programmes += 1
                start=epg_time(elem.get("start"))
                stop=epg_time(elem.get("stop"))
                if cid and start is not None and start<now+24*3600 and (stop is None or stop>now):
                    title=next(((c.text or "").strip() for c in elem if c.tag.rsplit("}",1)[-1]=="title"),"")
                    if title:
                        in_window_programmes += 1
                        shows[cid].append({"start":start,"stop":stop or start+3600,"title":title[:160]})
                elem.clear()
                root.clear()
    recovery = recover_mapped_listings(shows, now)
    local_recovered = recover_local_stations(shows, now)
    groups=[{} for _ in range(128)]
    for cid,items in shows.items():
        if any(ord(c)>127 for c in cid):
            continue  # Roku's byte-based ID hash is guaranteed for ASCII IDs.
        items.sort(key=lambda x:x["start"])
        groups[bucket(cid)][cid]=items[:12]
    # Preserve existing lookup keys / 128-shard format. Choose the largest
    # per-channel programme cap that fits every shard under Roku's 160KB limit.
    # The 24-hour filter is strict; channels with short shows may have more
    # programmes than one shard can safely hold.
    programme_cap = 12
    while True:
        max_shard_bytes = max(len(json.dumps({"channels":{key:items[:programme_cap]
            for key,items in shard.items()}}, ensure_ascii=False,
            separators=(",",":")).encode("utf-8")) for shard in groups)
        if max_shard_bytes < 160000 or programme_cap <= 1:
            break
        programme_cap -= 1
    groups = [{key:items[:programme_cap] for key,items in shard.items()}
              for shard in groups]
    destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    sizes=[]
    for i,items in enumerate(groups):
        encoded=json.dumps({"channels":items},ensure_ascii=False,separators=(",",":"))
        size=len(encoded.encode("utf-8"))
        if size>=160000:
            raise ValueError(f"Shard {i} is {size} bytes; not safe for the Roku loader")
        (destination/f"{i:03d}.json").write_text(encoded,encoding="utf-8")
        sizes.append(size)
    manifest={"schema":1,"generated_at":now,"buckets":128,"channel_ids":sum(map(len,groups)),"recovered_source_ids":recovery["source_matched"],"recovered_aliases":recovery["aliases_added"],"local_station_aliases":local_recovered,"source_channel_ids":len(source_ids),"source_programmes":total_programmes,"programmes_in_seven_day_window":in_window_programmes,"window_hours":24,"programmes_per_channel_cap":programme_cap,"max_bytes":max(sizes),"files":[f"{i:03d}.json" for i in range(128)]}
    (destination/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    if manifest["channel_ids"] < 500:
        print("WARNING: fewer than 500 IDs have current or upcoming listings; check source XMLTV and channel mappings.")
    print(json.dumps(manifest))
if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",default="v5-output/epg.xml.gz")
    parser.add_argument("--out",default="v5-output/roku-index")
    args=parser.parse_args()
    build(args.input,args.out)
