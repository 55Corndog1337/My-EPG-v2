#!/usr/bin/env python3
"""Save EPG2 numbered NCAAB listings to a stable, readable GitHub report."""
import gzip,json,re,urllib.request,xml.etree.ElementTree as ET
from datetime import datetime,timezone
from pathlib import Path
URL="https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg2.xml.gz"
OUT=Path(__file__).resolve().parent/"reports"/"ncaab-epg2-raw.json"
NUMBERS=set(range(1,26))|{36,37,38}
def run():
 req=urllib.request.Request(URL,headers={"User-Agent":"MyEPG/2.0"})
 with urllib.request.urlopen(req,timeout=60) as response:
  blob=response.read(60000001)
 if len(blob)>60000000:raise ValueError("EPG2 download too large")
 if blob.startswith(bytes((31,139))):blob=gzip.decompress(blob)
 root=ET.fromstring(blob)
 ids={}
 for ch in root.findall("channel"):
  cid=ch.get("id","")
  for name in [cid]+[e.text or "" for e in ch.findall("display-name")]:
   m=re.search(r"\bNCAAB\s*0*(\d{1,2})\b",name,re.I)
   if m and int(m.group(1)) in NUMBERS:
    ids.setdefault(int(m.group(1)),set()).add(cid)
 programs={}
 for p in root.findall("programme"):
  cid=p.get("channel","")
  if cid in {x for group in ids.values() for x in group}:
   programs.setdefault(cid,[]).append({"title":p.findtext("title",""),"start":p.get("start"),"stop":p.get("stop"),"description":p.findtext("desc","")})
 channels=[{"number":n,"xtream_channel":f"NCAAB {n:02d}","epg2_ids":sorted(ids.get(n,[])),"programmes":[dict(x,epg2_channel=cid) for cid in sorted(ids.get(n,[])) for x in programs.get(cid,[])]} for n in sorted(NUMBERS)]
 OUT.parent.mkdir(exist_ok=True)
 OUT.write_text(json.dumps({"updated_utc":datetime.now(timezone.utc).isoformat(),"source":URL,"channels":channels},indent=2)+"\n",encoding="utf-8")
 print("Wrote",OUT,"channels with programmes",sum(bool(c["programmes"]) for c in channels))
if __name__=="__main__":run()
