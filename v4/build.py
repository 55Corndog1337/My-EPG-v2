#!/usr/bin/env python3
"""V4-only complete-inventory XMLTV. Never changes V2 files."""
import csv, gzip, io, json, os, pathlib, re, urllib.request, zipfile, copy
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta, timezone

ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/"v4-output"
MAPPINGS=ROOT/"v4-mappings"
REPO=os.getenv("GITHUB_REPOSITORY","55Corndog1337/My-EPG-v2")
TOKEN=os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN","")
SOURCES={"epg2":"https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg2.xml.gz","epg6":"https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg6.xml.gz","epg37":"https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg37.xml.gz"}
def request(url):
 h={"User-Agent":"My-EPG-v4/2","Accept":"application/vnd.github+json"}
 if TOKEN and "api.github.com" in url:h["Authorization"]="Bearer "+TOKEN
 with urllib.request.urlopen(urllib.request.Request(url,headers=h),timeout=120) as r:return r.read()
def read_csv(data):
 return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig",errors="replace"))))
def val(row,*keys):
 d={k.lower().strip():(v or "").strip() for k,v in row.items() if k}
 return next((d[k.lower()] for k in keys if d.get(k.lower())),"")
def in_scope(row):
 g=val(row,"Group").upper()
 return any(k in g for k in ("USA","US |","UK |","CA |","CANADA","VIP"))
def inventory_from_zip(blob):
 try:z=zipfile.ZipFile(io.BytesIO(blob))
 except (zipfile.BadZipFile,ValueError):return []
 names=z.namelist()
 targets=[n for n in names if n.lower().endswith("all_channels_renamed.csv")]
 targets+= [n for n in names if n.lower().endswith(".csv") and ("xtream" in n.lower() or "inventory" in n.lower())]
 for n in targets:
  try:
   rows=read_csv(z.read(n))
   if len(rows)>100 and "StreamID" in rows[0]:return rows
  except Exception as e:print("Bad inventory",n,e)
 return []
def find_inventory():
 # Prefer the freshest inventory from GitHub Actions; no credentials or Xtream URLs embedded in code.
 local=[ROOT/"v4-input"/"sports-renamed"/"ALL_CHANNELS_Renamed.csv",ROOT/"v4-input"/"ALL_CHANNELS_Renamed.csv",ROOT/"v4"/"inventory.csv",ROOT/"xtream-inventory.csv",ROOT/"sports-renamed"/"ALL_CHANNELS_Renamed.csv"]
 for p in local:
  if p.exists():
   rows=read_csv(p.read_bytes())
   if len(rows)>100:return rows,str(p)
 try:
  payload=json.loads(request(f"https://api.github.com/repos/{REPO}/actions/artifacts?per_page=100"))
  artifacts=sorted((a for a in payload.get("artifacts",[]) if not a.get("expired")),key=lambda a:a.get("created_at",""),reverse=True)
  for a in artifacts:
   name=a.get("name","").lower()
   if not any(s in name for s in ("inventory","matching","xtream","report","channel")):continue
   try:
    rows=inventory_from_zip(request(a["archive_download_url"]))
    if rows:return rows,"artifact "+a["name"]
   except Exception as e:print("Artifact skipped",name,str(e)[:180])
 except Exception as e:print("Artifact discovery error",e)
 # Git tree inventory search (tracked inventory, if present)
 try:
  tree=json.loads(request(f"https://api.github.com/repos/{REPO}/git/trees/main?recursive=1"))
  paths=[e["path"] for e in tree.get("tree",[]) if e["type"]=="blob" and e["path"].lower().endswith(".csv") and any(x in e["path"].lower() for x in ("inventory","all_channels_renamed"))]
  for p in sorted(paths,key=lambda x:("all_channels_renamed" not in x.lower(),len(x))):
   try:
    rows=read_csv(request(f"https://raw.githubusercontent.com/{REPO}/main/{p}"))
    if len(rows)>100:return rows,"repository "+p
   except Exception:pass
 except Exception as e:print("Tree inventory error",e)
 raise RuntimeError("Full Xtream inventory unavailable. Refusing to overwrite V4 with a partial guide. Upload v4/inventory.csv or publish a current inventory/matching-reports artifact.")
def load_overrides():
 overrides={}
 for p in MAPPINGS.glob("*.csv"):
  try:rows=read_csv(p.read_bytes())
  except Exception:continue
  for r in rows:
   sid=val(r,"StreamID","Stream ID")
   if not sid:continue
   src=val(r,"V4 Source").lower()
   epg=val(r,"V4 EPG ID")
   status=val(r,"V4 Status","Validation").lower()
   title=val(r,"Programme Title","Static Title")
   if src=="static" or status=="static":overrides[sid]=("static","",title)
   elif src in SOURCES and epg:overrides[sid]=(src,epg,title)
 return overrides
def clean(name):
 name=re.sub(r"^(?:US|USA|UK|CA|VIP)\s*[-|:]\s*","",name,flags=re.I)
 return re.sub(r"\s+"," ",name).strip() or "Unknown channel"
def title_for(row):
 raw=val(row,"OriginalChannelName","ChannelName","NewChannelName")
 group=val(row,"Group").upper()
 if any(x in group for x in ("NFL","NBA","NHL","MLB","MILB","MLS","AHL","WNBA","NCAA","ESPN PLUS","FLO SPORTS","BTN")):
  if ":" in raw:
   detail=raw.split(":",1)[1].strip()
   if detail:return clean(detail)
 return clean(val(row,"NewChannelName","ChannelName","OriginalChannelName"))
def load_epgs(rows,overrides):
 needed=defaultdict(set)
 for row in rows:
  sid=val(row,"StreamID")
  if sid in overrides:
   src,epgid,_=overrides[sid]
   if src in SOURCES:needed[src].add(epgid)
  else:
   src=val(row,"EPGSource").lower()
   epgid=val(row,"SourceChannelID")
   if src in SOURCES and epgid:needed[src].add(epgid)
   else:
    provider=val(row,"EPGID","ProviderID")
    if provider:
     for s in SOURCES:needed[s].add(provider)
 programmes=defaultdict(list)
 for source,url in SOURCES.items():
  try:
   print("Downloading",source,flush=True)
   data=request(url)
   if data[:2]==b"\x1f\x8b":data=gzip.decompress(data)
   stream=io.BytesIO(data)
   count=0
   for event,item in ET.iterparse(stream,events=("end",)):
    if item.tag!="programme":continue
    cid=item.get("channel")
    if cid in needed[source]:
     programmes[(source,cid)].append(copy.deepcopy(item));count+=1
    item.clear()
   print(source,"programmes matched",count,flush=True)
  except Exception as e:print("Source failure",source,e,flush=True)
 return programmes
def generate():
 rows,inventory_source=find_inventory()
 rows=[r for r in rows if val(r,"StreamID") and in_scope(r)]
 if len(rows)<1000:raise RuntimeError(f"Inventory only has {len(rows)} scoped channels, refusing incomplete V4 publication")
 print("Inventory",inventory_source,"channels",len(rows),flush=True)
 overrides=load_overrides()
 programmes=load_epgs(rows,overrides)
 tv=ET.Element("tv",{"generator-info-name":"My-EPG V4 full inventory"})
 now=datetime.now(timezone.utc)
 start=now.strftime("%Y%m%d%H%M%S +0000")
 end=(now+timedelta(days=1)).strftime("%Y%m%d%H%M%S +0000")
 counts={"inventory_source":inventory_source,"channels":0,"programmes":0,"fallback_channels":0,"mapped_channels":0,"categories":{}}
 seen=set()
 for row in rows:
  sid=val(row,"StreamID")
  if sid in seen:continue
  seen.add(sid)
  group=val(row,"Group")
  counts["categories"][group]=counts["categories"].get(group,0)+1
  name=val(row,"NewChannelName","ChannelName","OriginalChannelName") or "Stream "+sid
  title=title_for(row)
  source=val(row,"EPGSource").lower()
  epgid=val(row,"SourceChannelID")
  if sid in overrides:
   source,epgid,static_title=overrides[sid]
   if static_title:title=static_title
  elif source not in SOURCES or not epgid:
   source="";epgid=val(row,"EPGID","ProviderID")
  cid="v4."+sid
  ch=ET.SubElement(tv,"channel",id=cid)
  ET.SubElement(ch,"display-name").text=title
  ET.SubElement(ch,"display-name").text=clean(name)
  events=programmes.get((source,epgid),[]) if source in SOURCES else []
  if not events and source!="static" and epgid:
   for candidate in ("epg37","epg6","epg2"):
    if programmes.get((candidate,epgid)):
     events=programmes[(candidate,epgid)];break
  if events:
   counts["mapped_channels"]+=1
   for original in events:
    p=copy.deepcopy(original);p.set("channel",cid);tv.append(p);counts["programmes"]+=1
  else:
   p=ET.SubElement(tv,"programme",start=start,stop=end,channel=cid)
   ET.SubElement(p,"title",lang="en").text=title
   ET.SubElement(p,"desc",lang="en").text="V4: no verified schedule available; channel retained for later correction"
   counts["fallback_channels"]+=1
  counts["channels"]+=1
 OUT.mkdir(parents=True,exist_ok=True)
 with gzip.open(OUT/"epg.xml.gz","wb",compresslevel=6) as f:
  f.write(ET.tostring(tv,encoding="utf-8",xml_declaration=True))
 (OUT/"coverage.json").write_text(json.dumps(counts,indent=2),encoding="utf-8")
 print("V4 generated",json.dumps({k:v for k,v in counts.items() if k!="categories"}),flush=True)
if __name__=="__main__":generate()
