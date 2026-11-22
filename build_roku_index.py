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
                if cid and start is not None and start<now+7*24*3600 and (stop is None or stop>now):
                    title=next(((c.text or "").strip() for c in elem if c.tag.rsplit("}",1)[-1]=="title"),"")
                    if title:
                        in_window_programmes += 1
                        shows[cid].append({"start":start,"stop":stop or start+3600,"title":title[:160]})
                elem.clear()
                root.clear()
    groups=[{} for _ in range(128)]
    for cid,items in shows.items():
        if any(ord(c)>127 for c in cid):
            continue  # Roku's byte-based ID hash is guaranteed for ASCII IDs.
        items.sort(key=lambda x:x["start"])
        groups[bucket(cid)][cid]=items[:6]
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
    manifest={"schema":1,"generated_at":now,"buckets":128,"channel_ids":sum(map(len,groups)),"source_channel_ids":len(source_ids),"source_programmes":total_programmes,"programmes_in_seven_day_window":in_window_programmes,"window_days":7,"max_bytes":max(sizes),"files":[f"{i:03d}.json" for i in range(128)]}
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
