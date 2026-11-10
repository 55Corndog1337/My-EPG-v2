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
 # Reuse V4 JSON mapping work (FloSports, ESPN+, BTN+, 24/7, etc.)
 # instead of limiting V4 to the three original CSV mapping sets.
 for p in sorted(MAPPINGS.glob("*.json")):
  try:
   doc=json.loads(p.read_text(encoding="utf-8"))
   items=doc.get("mappings",[]) if isinstance(doc,dict) else []
   for item in items:
    sid=str(item.get("xtream_stream_id") or item.get("stream_id") or "").strip()
    if not sid:continue
    src=(item.get("source") or item.get("epg_source") or "").lower()
    epgid=item.get("source_channel_id") or ""
    title=item.get("clean_programme_title") or ""
    if src in SOURCES and epgid:
     if sid not in overrides or overrides[sid][0]=="static":
      overrides[sid]=(src,epgid,title)
    elif title and sid not in overrides:
     overrides[sid]=("static","",title)
  except Exception as e:print("JSON mapping skipped",p.name,e,flush=True)
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
def norm(text):
 text=clean(text).lower()
 text=re.sub(r"[◉★™®]", "", text)
 text=re.sub(r"\b(?:uhd|fhd|hd|sd|4k|1080p|720p|hevc|h265|h264)\b", "", text)
 text=re.sub(r"[^a-z0-9]+", "", text)
 return text
def sports_event(row):
 group=val(row,"Group").upper()
 return any(x in group for x in ("NFL","NBA","NHL","MLB","MILB","MLS","AHL","WNBA","NCAA","ESPN PLUS","FLO SPORTS","BTN+","PPV","LIVE EVENT","PEACOCK","PARAMOUNT+","SN+","TSN+","VICTORY +"))
def event_name_keys(row):
 # Match only descriptive, event-specific names; never generic numbered slots.
 keys=[]
 for label in (val(row,"OriginalChannelName"),val(row,"ChannelName"),val(row,"NewChannelName")):
  label=clean(label)
  if ":" in label:label=label.split(":",1)[1].strip()
  label=re.sub(r"^(?:peacock|paramount\\+?)\\s*[-:]?\\s*", "", label,flags=re.I)
  key=norm(label)
  if len(key)>=12 and not re.fullmatch(r"(?:peacock|paramount|event|live|game|channel|stream|ppv)\\d*",key):
   keys.append(key)
 return list(dict.fromkeys(keys))
def load_epgs(rows,overrides):
 # Index the actual channel catalogs first, so EPG 37, 2, and 6 can
 # fill holes even when the provider's EPG ID differs from the source ID.
 catalogs={}
 for source,url in SOURCES.items():
  try:
   print("Downloading",source,flush=True)
   data=request(url)
   if data[:2]==b"\x1f\x8b":data=gzip.decompress(data)
   channels={}
   for _,item in ET.iterparse(io.BytesIO(data),events=("end",)):
    if item.tag=="channel":
     cid=item.get("id")
     if cid:
      names=[x.text or "" for x in item.findall("display-name")]
      channels[cid]=names
     item.clear()
    elif item.tag=="programme":item.clear()
   catalogs[source]=(data,channels)
   print(source,"catalog channels",len(channels),flush=True)
  except Exception as e:print("Source failure",source,str(e),flush=True)
 # Export the real source catalog for manual Peacock/Paramount+ matching.
 # Each row includes the source channel ID, display name and sample programme titles.
 catalog_path=OUT/"epg-source-catalog.csv"
 OUT.mkdir(parents=True,exist_ok=True)
 with catalog_path.open("w",newline="",encoding="utf-8-sig") as fh:
  writer=csv.writer(fh)
  writer.writerow(["EPG Source","Source Channel ID","Source Display Names","Sample Programme Titles"])
  for src,(blob,channels) in catalogs.items():
   samples=defaultdict(list)
   for _,item in ET.iterparse(io.BytesIO(blob),events=("end",)):
    if item.tag!="programme":continue
    cid=item.get("channel")
    if cid in channels and len(samples[cid])<3:
     title=item.findtext("title") or ""
     if title and title not in samples[cid]:samples[cid].append(title)
    item.clear()
   for cid,names in channels.items():
    writer.writerow([src,cid," | ".join(names)," | ".join(samples.get(cid,[]))])
 print("Wrote real EPG source catalog",catalog_path,flush=True)
 by_id={}
 by_name={}
 for source,(data,channels) in catalogs.items():
  for cid,names in channels.items():
   by_id[(source,cid.lower())]=cid
   for name in names:
    key=norm(name)
    if key:by_name.setdefault((source,key),set()).add(cid)
 wanted=defaultdict(set)
 decisions={}
 match_counts=defaultdict(int)
 for row in rows:
  sid=val(row,"StreamID")
  if not sid:continue
  explicit=overrides.get(sid)
  if explicit and explicit[0]=="static":
   decisions[sid]=None;continue
  preferred=[]
  if explicit and explicit[0] in SOURCES:preferred.append((explicit[0],explicit[1]))
  invsrc=val(row,"EPGSource").lower()
  invid=val(row,"SourceChannelID")
  if invsrc in SOURCES and invid:preferred.append((invsrc,invid))
  provider=val(row,"EPGID","ProviderID")
  if provider:
   for src in ("epg37","epg2","epg6"):preferred.append((src,provider))
  chosen=None
  for src,cid in preferred:
   canonical=by_id.get((src,cid.lower()))
   if canonical:
    chosen=(src,canonical,"id");break
  # Never infer event-channel schedules from generic channel names:
  # Game 01, ESPN+ 01, FloSports 01, etc. require event-specific mapping.
  group=val(row,"Group").upper()
  if not chosen and ("PEACOCK" in group or "PARAMOUNT+" in group):
   # Streaming slots are often numbered; only accept an exact unique
   # descriptive event name, not "Peacock 01" or "Paramount+ 01".
   for src in ("epg2","epg6","epg37"):
    candidates=set()
    for key in event_name_keys(row):candidates.update(by_name.get((src,key),set()))
    if len(candidates)==1:
     chosen=(src,next(iter(candidates)),"event_name");break
  if not chosen and not sports_event(row):
   keys=[]
   for label in (val(row,"OriginalChannelName"),val(row,"ChannelName"),val(row,"NewChannelName")):
    key=norm(label)
    if key and key not in keys:keys.append(key)
   for src in ("epg37","epg2","epg6"):
    candidates=set()
    for key in keys:candidates.update(by_name.get((src,key),set()))
    if len(candidates)==1:
     chosen=(src,next(iter(candidates)),"name");break
  decisions[sid]=chosen
  if chosen:
   wanted[chosen[0]].add(chosen[1])
   match_counts[chosen[0]+"_"+chosen[2]]+=1
 programmes=defaultdict(list)
 for source,(data,channels) in catalogs.items():
  if not wanted[source]:continue
  count=0
  for _,item in ET.iterparse(io.BytesIO(data),events=("end",)):
   if item.tag!="programme":continue
   cid=item.get("channel")
   if cid in wanted[source]:
    programmes[(source,cid)].append(copy.deepcopy(item));count+=1
   item.clear()
  print(source,"matched programmes",count,flush=True)
 print("Source decisions",dict(match_counts),flush=True)
 return programmes,decisions,dict(match_counts)
def ahl_schedule():
 p=MAPPINGS/"ahl-season-2026-27.csv"
 result=defaultdict(list)
 if not p.exists():return result
 for r in read_csv(p.read_bytes()):
  sid=val(r,"StreamID")
  try:
   st=datetime.fromisoformat(val(r,"StartUTC")).astimezone(timezone.utc)
   en=datetime.fromisoformat(val(r,"EndUTC")).astimezone(timezone.utc)
   if en>st:result[sid].append((st,en,val(r,"Event","Title")))
  except (ValueError,TypeError):continue
 for games in result.values():games.sort(key=lambda x:x[0])
 return result
def add_programme(tv,cid,begin,end,title,desc=""):
 p=ET.SubElement(tv,"programme",start=begin.strftime("%Y%m%d%H%M%S +0000"),stop=end.strftime("%Y%m%d%H%M%S +0000"),channel=cid)
 ET.SubElement(p,"title",lang="en").text=title
 if desc:ET.SubElement(p,"desc",lang="en").text=desc
def add_ahl(tv,cid,games,now,horizon):
 cursor=now
 added=0
 upcoming=[g for g in games if g[1]>now and g[0]<horizon]
 for st,en,event in upcoming:
  if st>cursor:
   label="Next Game: "+event+" ("+st.strftime("%B %d, %I:%M %p UTC")+")"
   add_programme(tv,cid,cursor,min(st,horizon),label);added+=1
  if en>max(st,cursor):
   add_programme(tv,cid,max(st,cursor),min(en,horizon),event);added+=1
  cursor=max(cursor,en)
 if cursor<horizon:
  add_programme(tv,cid,cursor,horizon,"Event concluded" if upcoming else "No Game Scheduled");added+=1
 return added
def generate():
 rows,inventory_source=find_inventory()
 rows=[r for r in rows if val(r,"StreamID") and in_scope(r)]
 if len(rows)<1000:raise RuntimeError(f"Inventory only has {len(rows)} scoped channels, refusing incomplete V4 publication")
 print("Inventory",inventory_source,"channels",len(rows),flush=True)
 overrides=load_overrides()
 programmes,decisions,match_counts=load_epgs(rows,overrides)
 ahl=ahl_schedule()
 tv=ET.Element("tv",{"generator-info-name":"My-EPG V4 full inventory"})
 now=datetime.now(timezone.utc)
 start=now.strftime("%Y%m%d%H%M%S +0000")
 end=(now+timedelta(days=1)).strftime("%Y%m%d%H%M%S +0000")
 counts={"inventory_source":inventory_source,"channels":0,"programmes":0,"fallback_channels":0,"mapped_channels":0,"categories":{},"source_matches":match_counts,"scheduled_by_source":{},"unmatched_by_category":{}}
 seen=set()
 for row in rows:
  sid=val(row,"StreamID")
  if sid in seen:continue
  seen.add(sid)
  group=val(row,"Group")
  counts["categories"][group]=counts["categories"].get(group,0)+1
  name=val(row,"NewChannelName","ChannelName","OriginalChannelName") or "Stream "+sid
  title=title_for(row)
  explicit=overrides.get(sid)
  if explicit and explicit[2]:title=explicit[2]
  selected=decisions.get(sid)
  source,epgid=(selected[0],selected[1]) if selected else ("","")
  cid="v4."+sid
  ch=ET.SubElement(tv,"channel",id=cid)
  ET.SubElement(ch,"display-name").text=title
  ET.SubElement(ch,"display-name").text=clean(name)
  events=programmes.get((source,epgid),[]) if selected else []
  if "AHL" in group.upper() and sid in ahl:
   horizon=now+timedelta(days=7)
   n=add_ahl(tv,cid,ahl[sid],now,horizon)
   counts["mapped_channels"]+=1
   counts["programmes"]+=n
   counts["scheduled_by_source"]["ahl-season-csv"]=counts["scheduled_by_source"].get("ahl-season-csv",0)+1
  elif "24/7" in group.upper() and not events:
   add_programme(tv,cid,now,now+timedelta(days=1),title,"24/7 repeating channel")
   counts["mapped_channels"]+=1
   counts["programmes"]+=1
   counts["scheduled_by_source"]["24-7-static"]=counts["scheduled_by_source"].get("24-7-static",0)+1
  elif events:
   counts["mapped_channels"]+=1
   counts["scheduled_by_source"][source]=counts["scheduled_by_source"].get(source,0)+1
   for original in events:
    p=copy.deepcopy(original);p.set("channel",cid);tv.append(p);counts["programmes"]+=1
  else:
   p=ET.SubElement(tv,"programme",start=start,stop=end,channel=cid)
   ET.SubElement(p,"title",lang="en").text=title
   ET.SubElement(p,"desc",lang="en").text="V4: no verified schedule available; channel retained for later correction"
   counts["fallback_channels"]+=1
   counts["unmatched_by_category"][group]=counts["unmatched_by_category"].get(group,0)+1
  counts["channels"]+=1
 OUT.mkdir(parents=True,exist_ok=True)
 with gzip.open(OUT/"epg.xml.gz","wb",compresslevel=6) as f:
  f.write(ET.tostring(tv,encoding="utf-8",xml_declaration=True))
 (OUT/"coverage.json").write_text(json.dumps(counts,indent=2),encoding="utf-8")
 print("V4 generated",json.dumps({k:v for k,v in counts.items() if k!="categories"}),flush=True)
if __name__=="__main__":generate()
