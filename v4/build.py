#!/usr/bin/env python3
"""Independent V4 XMLTV builder. Never reads or writes the V2 output."""
import csv, gzip, io, os, pathlib, re, urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
MAPPINGS = ROOT / "v4-mappings"
OUTPUT = ROOT / "v4-output"
SOURCES = {
 "epg2": "https://github.com/ferteque/Curated-M3U-Repository/raw/refs/heads/main/epg2.xml.gz",
 "epg6": "https://github.com/ferteque/Curated-M3U-Repository/raw/refs/heads/main/epg6.xml.gz",
 "epg37": "https://github.com/ferteque/Curated-M3U-Repository/raw/refs/heads/main/epg37.xml.gz",
}
def pick(row, *names):
 lower = {k.lower().strip(): (v or "").strip() for k,v in row.items() if k}
 return next((lower[n.lower()] for n in names if lower.get(n.lower())), "")
def load_rows():
 files = ["usa-documentary-approved-48.csv","usa-premium-175-reviewed.csv","usa-network-locals-884.csv","usa-entertainment-251-working.csv"]
 rows = {}
 for filename in files:
  p=MAPPINGS/filename
  if not p.exists():
   print("SKIP missing",p)
   continue
  with p.open(encoding="utf-8-sig",newline="") as f:
   for r in csv.DictReader(f):
    sid=pick(r,"StreamID","Stream ID","stream_id")
    if not sid: continue
    name=pick(r,"Original Channel","OriginalChannelName","Channel Name","Original Channel Name","Channel","Name") or ("Stream "+sid)
    source=pick(r,"V4 Source","Source","V4_Source").lower()
    epgid=pick(r,"V4 EPG ID","EPG ID","V4_EPG_ID")
    title=pick(r,"Programme Title","Static Title") or re.sub(r"^(US|USA)\s*[-|:]\s*","",name,flags=re.I)
    status=pick(r,"V4 Status","Validation","Audit Status").lower()
    if source not in SOURCES or not epgid or status in ("static","unresolved","needs_review"):
     source="static";epgid=""
    rows[sid]=(name,source,epgid,title)
 return rows
def source_data(wanted):
 found=defaultdict(list)
 for source,url in SOURCES.items():
  if not any(s==source for _,s,_,_ in wanted.values()):continue
  try:
   print("Downloading",source,flush=True)
   with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"V4-XMLTV/1.0"}),timeout=100) as resp:
    raw=resp.read()
   data=gzip.decompress(raw) if raw[:2]==b"\x1f\x8b" else raw
   root=ET.fromstring(data)
   keys={epgid for _,s,epgid,_ in wanted.values() if s==source}
   for item in root.findall("programme"):
    if item.get("channel") in keys: found[(source,item.get("channel"))].append(item)
   print(source,"matched",len(found),flush=True)
  except Exception as exc: print("WARNING",source,str(exc),flush=True)
 return found
def build():
 rows=load_rows()
 if not rows: raise SystemExit("No V4 mapping CSVs found; refusing to publish empty guide")
 programmes=source_data(rows)
 tv=ET.Element("tv",{"generator-info-name":"My-EPG V4 independent"})
 now=datetime.now(timezone.utc)
 start=now.strftime("%Y%m%d%H%M%S +0000")
 end=(now+timedelta(days=1)).strftime("%Y%m%d%H%M%S +0000")
 counts={"channels":len(rows),"source_programmes":0,"fallback":0}
 for sid,(name,source,epgid,title) in rows.items():
  channel_id="v4."+sid
  ch=ET.SubElement(tv,"channel",id=channel_id)
  ET.SubElement(ch,"display-name").text=title
  events=programmes.get((source,epgid),[]) if source!="static" else []
  if events:
   for original in events:
    p=ET.SubElement(tv,"programme",start=original.get("start",start),stop=original.get("stop",end),channel=channel_id)
    for child in original: p.append(ET.fromstring(ET.tostring(child,encoding="utf-8")))
    counts["source_programmes"]+=1
  else:
   p=ET.SubElement(tv,"programme",start=start,stop=end,channel=channel_id)
   ET.SubElement(p,"title",lang="en").text=title
   ET.SubElement(p,"desc",lang="en").text="V4 static or awaiting verified programme listings"
   counts["fallback"]+=1
 OUTPUT.mkdir(parents=True,exist_ok=True)
 dest=OUTPUT/"epg.xml.gz"
 with gzip.open(dest,"wb",compresslevel=6) as f:f.write(ET.tostring(tv,encoding="utf-8",xml_declaration=True))
 print("Wrote",dest,counts,flush=True)
if __name__=="__main__":build()
