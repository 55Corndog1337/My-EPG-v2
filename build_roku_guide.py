#!/usr/bin/env python3
"""Build Roku-friendly JSON from the published gzipped combined XMLTV guide."""
import argparse, gzip, json, urllib.request, xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

DEFAULT_URL = "https://55Corndog1337.github.io/My-EPG-v2/v5-output/epg.xml.gz"

def build(source, output, hours=24, cap=4):
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=hours)
    shows = defaultdict(list)
    names = {}
    def parse(v):
        date, *tz = v.split()
        dt = datetime.strptime((date+"000000")[:14], "%Y%m%d%H%M%S")
        z = tz[0] if tz else "+0000"
        minutes = (1 if z[0]=="+" else -1)*(int(z[1:3])*60+int(z[3:5]))
        return dt.replace(tzinfo=timezone(timedelta(minutes=minutes))).astimezone(timezone.utc)
    req = urllib.request.Request(source, headers={"User-Agent":"StreamDeckTV-Guide/4.3"})
    with urllib.request.urlopen(req, timeout=180) as raw:
        stream = gzip.GzipFile(fileobj=raw)
        events = ET.iterparse(stream, events=("start", "end"))
        _, root = next(events)
        for event, elem in events:
            if event != "end":
                continue
            tag = elem.tag.rsplit("}", 1)[-1]
            if tag == "channel":
                cid = (elem.get("id") or "").strip().lower()
                for x in elem:
                    if x.tag.rsplit("}",1)[-1] == "display-name":
                        n = (x.text or "").strip().lower()
                        if n and cid: names.setdefault(n, cid)
            elif tag == "programme":
                cid = (elem.get("channel") or "").strip().lower()
                try:
                    a = parse(elem.get("start",""))
                    b = parse(elem.get("stop","")) if elem.get("stop") else a+timedelta(hours=1)
                    if cid and a < cutoff and b > now:
                        title = next(((x.text or "").strip() for x in elem if x.tag.rsplit("}",1)[-1]=="title"), "") or "Programme"
                        shows[cid].append({"title":title,"start":int(a.timestamp()),"stop":int(b.timestamp())})
                except (ValueError, TypeError, IndexError):
                    pass
            if tag in ("channel", "programme"):
                elem.clear()
                root.clear()
    by_channel = {k:sorted(v,key=lambda x:x["start"])[:cap] for k,v in shows.items()}
    data = {"generated_at":int(now.timestamp()),"channels":by_channel,"aliases":{n:c for n,c in names.items() if c in by_channel}}
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    print(f"Created {path} with {len(by_channel)} channels")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--source",default=DEFAULT_URL)
    p.add_argument("--output",default="v5-output/roku-guide.json")
    a=p.parse_args()
    build(a.source,a.output)
