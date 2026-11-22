#!/usr/bin/env python3
"""Build compact Roku JSON per actual playlist group, without exporting stream URLs."""
import os, re, json, gzip, argparse, urllib.request, xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

def stream(path):
    if path.startswith(("https://","http://")):
        return urllib.request.urlopen(urllib.request.Request(path,headers={"User-Agent":"StreamDeckTV/1.0"}),timeout=120)
    return open(path,"rb")

def playlist(path):
    with stream(path) as f: raw=f.read(35000000).decode("utf-8-sig","replace")
    if not raw.lstrip().startswith("#EXTM3U"): raise ValueError("Not an extended M3U")
    items=[]; name=""; attrs={}; group="Uncategorized"
    for line in raw.splitlines():
        line=line.strip()
        if line.startswith("#EXTINF"):
            attrs=dict(re.findall(r'([\w-]+)\s*=\s*"([^"]*)"',line))
            name=line.partition(",")[2].strip() or attrs.get("tvg-name","Untitled")
            group=attrs.get("group-title") or "Uncategorized"
        elif line.startswith("#EXTGRP:") and group=="Uncategorized":
            group=line.partition(":")[2].strip() or group
        elif name and line and not line.startswith("#"):
            items.append({"name":name,"group":group,"epg_id":attrs.get("tvg-id",""),"ordinal":len(items)+1})
            name="";attrs={};group="Uncategorized"
    if not items: raise ValueError("No playlist channels found")
    return items

def when(s):
    m=re.match(r"^(\d{14})(?:\s*([+-])(\d\d)(\d\d))?",s or "")
    if not m:return None
    t=datetime.strptime(m.group(1),"%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    if m.group(2):
        mins=(int(m.group(3))*60+int(m.group(4)))*(1 if m.group(2)=="+" else -1)
        t-=timedelta(minutes=mins)
    return int(t.timestamp())

def programmes(path,wanted,now):
    output=defaultdict(list)
    with stream(path) as raw:
        body=gzip.GzipFile(fileobj=raw) if path.split("?")[0].lower().endswith(".gz") else raw
        events=ET.iterparse(body,events=("start","end"))
        _,root=next(events)
        for event,e in events:
            if event!="end":continue
            tag=e.tag.rsplit("}",1)[-1]
            if tag=="programme":
                cid=(e.get("channel") or "").lower()
                if cid in wanted:
                    a,b=when(e.get("start")),when(e.get("stop"))
                    if a is not None and a<now+172800 and (b is None or b>now):
                        title=next(((x.text or "").strip() for x in e if x.tag.rsplit("}",1)[-1]=="title"),"")
                        output[cid].append({"title":title or "Programme","start":a,"stop":b or a+3600})
            if tag in ("channel","programme"):
                e.clear();root.clear()
    return {k:sorted(v,key=lambda x:x["start"])[:12] for k,v in output.items()}

def build(playlist_source,epg_source,outdir,limit=200):
    if not 1<=limit<=400:raise ValueError("chunk size out of range")
    items=playlist(playlist_source);groups=defaultdict(list)
    for c in items:groups[c["group"]].append(c)
    names=(["00 - Favorites"] if "00 - Favorites" in groups else [])+[x for x in groups if x!="00 - Favorites"]
    now=int(datetime.now(timezone.utc).timestamp())
    data=programmes(epg_source,{c["epg_id"].lower() for c in items if c["epg_id"]},now)
    out=Path(outdir);out.mkdir(parents=True,exist_ok=True)
    manifest={"schema":1,"generated_at":now,"channel_count":len(items),"categories":[]};created=set();matched=0
    for group in names:
        g=groups[group];entry={"name":group,"channel_count":len(g),"parts":[]}
        slug=re.sub(r"[^a-z0-9]+","-",group.lower()).strip("-")[:45] or "group"
        for i in range(0,len(g),limit):
            part=g[i:i+limit]; filename=f"{slug}-{i//limit+1:02d}.json"
            if filename in created:raise ValueError("Category filename collision: "+filename)
            created.add(filename)
            matched+=sum(bool(data.get(c["epg_id"].lower())) for c in part)
            payload={"schema":1,"category":group,"generated_at":now,
                "channels":{c["epg_id"].lower():data[c["epg_id"].lower()] for c in part if data.get(c["epg_id"].lower())},
                "playlist_channels":[{"ordinal":c["ordinal"],"name":c["name"],"epg_id":c["epg_id"]} for c in part]}
            p=out/filename;p.write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
            entry["parts"].append({"file":filename,"channel_count":len(part),"bytes":p.stat().st_size})
        manifest["categories"].append(entry)
    for old in out.glob("*.json"):
        if old.name not in created|{"manifest.json","report.json"}:old.unlink()
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf-8")
    report={"generated_at":now,"total_channels":len(items),"categories":len(names),"chunks":len(created),"matched_programme_channels":matched,"unmatched":len(items)-matched}
    (out/"report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report))
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--playlist",default=os.environ.get("ROKU_M3U_URL",""))
    p.add_argument("--epg",default="v5-output/epg.xml.gz")
    p.add_argument("--out",default="v5-output/roku-categories")
    p.add_argument("--chunk-size",type=int,default=200)
    a=p.parse_args()
    if not a.playlist:p.error("Set private repository secret ROKU_M3U_URL to refresh new channels")
    build(a.playlist,a.epg,a.out,a.chunk_size)
