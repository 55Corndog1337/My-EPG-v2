#!/usr/bin/env python3
"""Collect a private Xtream channel inventory and public XMLTV source snapshots."""
import os, json, gzip, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone

SOURCES = {
 "2": "https://github.com/ferteque/Curated-M3U-Repository/raw/refs/heads/main/epg2.xml.gz",
 "6": "https://github.com/ferteque/Curated-M3U-Repository/raw/refs/heads/main/epg6.xml.gz",
 "37": "https://github.com/ferteque/Curated-M3U-Repository/raw/refs/heads/main/epg37.xml.gz",
}
def get(url):
 req=urllib.request.Request(url,headers={"User-Agent":"My-EPG-v2/1.0"})
 with urllib.request.urlopen(req,timeout=120) as response: return response.read()
def collect_channels():
 base=os.environ["XTREAM_URL"].strip().rstrip("/")
 if not base.startswith(("https://","http://")): base="http://"+base
 query=urllib.parse.urlencode({"username":os.environ["XTREAM_USERNAME"],"password":os.environ["XTREAM_PASSWORD"],"action":"get_live_categories"})
 categories=json.loads(get(base+"/player_api.php?"+query))
 selected={str(c["category_id"]):c.get("category_name","") for c in categories if any(k in c.get("category_name","").upper() for k in ("US ","USA","UK ","CA ","CANADA","AM | US","AM | CA","EU | UK","AM - US","AM - CA","EU - UK"))}
 query=urllib.parse.urlencode({"username":os.environ["XTREAM_USERNAME"],"password":os.environ["XTREAM_PASSWORD"],"action":"get_live_streams"})
 streams=json.loads(get(base+"/player_api.php?"+query))
 rows=[{"stream_id":s.get("stream_id"),"name":s.get("name"),"category_id":str(s.get("category_id")),"category":selected[str(s.get("category_id"))],"epg_channel_id":s.get("epg_channel_id")} for s in streams if str(s.get("category_id")) in selected]
 Path("private").mkdir(exist_ok=True)
 Path("private/channels.json").write_text(json.dumps({"generated_at":datetime.now(timezone.utc).isoformat(),"channels":rows},ensure_ascii=False),encoding="utf-8")
 print(f"Private channel inventory prepared: {len(rows)} channels across {len(selected)} categories")
def collect_epg():
 Path("data").mkdir(exist_ok=True)
 for key,url in SOURCES.items():
  raw=get(url)
  xml=gzip.decompress(raw) if raw[:2]==b"\\x1f\\x8b" else raw
  root=ET.fromstring(xml)
  if root.tag!="tv": raise ValueError(f"EPG {key}: not XMLTV")
  channels=[{"id":c.get("id"),"names":[n.text for n in c.findall("display-name") if n.text]} for c in root.findall("channel")]
  programmes=[{"channel":p.get("channel"),"start":p.get("start"),"stop":p.get("stop"),"title":p.findtext("title") or "","desc":p.findtext("desc") or ""} for p in root.findall("programme")]
  output={"source":key,"generated_at":datetime.now(timezone.utc).isoformat(),"channels":channels,"programmes":programmes}
  Path(f"data/epg{key}.json").write_text(json.dumps(output,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
  print(f"EPG {key}: {len(channels)} channels, {len(programmes)} programmes")
if __name__=="__main__":
 collect_channels()
 collect_epg()
