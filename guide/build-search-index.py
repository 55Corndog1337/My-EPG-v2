#!/usr/bin/env python3
"""Extract compact current/upcoming listings from the published combined XMLTV."""
import gzip,json,datetime,xml.etree.ElementTree as ET
from pathlib import Path
src=Path("v4-output/epg.xml.gz")
dst=Path("guide/programmes.json")
now=datetime.datetime.now(datetime.timezone.utc)
cutoff=now+datetime.timedelta(days=2)
def parse(s):
    if not s:return None
    try:return datetime.datetime.strptime(s[:14],"%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone(datetime.timedelta(hours=int(s[15:18]),minutes=int(s[18:20])*(1 if s[15]=="+" else -1)))) if len(s)>=20 and s[15] in "+-" else datetime.datetime.strptime(s[:14],"%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)
    except (ValueError,TypeError):return None
if not src.exists():raise SystemExit("Combined EPG missing")
with gzip.open(src,"rb") as f:root=ET.parse(f).getroot()
names={c.get("id"):next((n.text for n in c.findall("display-name") if n.text),c.get("id")) for c in root.findall("channel")}
rows=[]
for p in root.findall("programme"):
    start,stop=parse(p.get("start")),parse(p.get("stop"))
    if not start or not stop or stop<=now or start>=cutoff:continue
    title=p.findtext("title") or ""
    if not title:continue
    cid=p.get("channel")
    rows.append([names.get(cid,cid),title,int(start.timestamp()),int(stop.timestamp())])
dst.parent.mkdir(parents=True,exist_ok=True)
dst.write_text(json.dumps({"generated":now.isoformat(),"programmes":rows},ensure_ascii=False,separators=(",",":")),encoding="utf-8")
print(f"Indexed {len(rows)} current/upcoming programmes")
