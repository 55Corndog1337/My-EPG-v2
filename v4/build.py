# V4 scheduled publication trigger 2026-11-11 12:00 EST
# V4 scheduled publication trigger 2026-11-11 06:04 EST; no mapping changes.
#!/usr/bin/env python3
# V4 scheduled publication refresh trigger; generator behavior unchanged.
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
  label=re.sub(r"^(?:peacock|paramount\+?)\s*[-:]?\s*", "", label,flags=re.I)
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
  # ESPN+ slots 1-600: EPG2 exclusively. Never fall back to EPG6/37.
  group=val(row,"Group").upper()
  raw=val(row,"OriginalChannelName","ChannelName","NewChannelName")
  slot=re.search(r"ESPN\\s*(?:\\+|PLUS)\\s*0*(\\d{1,3})\\b",raw,re.I)
  provider_slot=re.fullmatch(r"ESPN(?:\\.PLUS|Plus)\\.(\\d{1,3})",val(row,"EPGID","ProviderID"),re.I)
  number=int(slot.group(1)) if slot else (int(provider_slot.group(1)) if provider_slot else 0)
  is_espn="ESPN PLUS" in group or (provider_slot is not None)
  if is_espn and 1<=number<=600:
   candidates=[f"ESPNPlus.{number}",f"ESPN.PLUS.{number}",f"ESPN+.{number}"]
   if explicit and explicit[0]=="epg2":candidates.append(explicit[1])
   if invsrc=="epg2" and invid:candidates.append(invid)
   for candidate in candidates:
    canonical=by_id.get(("epg2",candidate.lower()))
    if canonical:
     chosen=("epg2",canonical,"espn_slot");break
   if not chosen:
    for candidate in (f"ESPN+ {number:03d}",f"ESPN+ {number}",f"ESPN PLUS {number:03d}",f"ESPN PLUS {number}"):
     matches=by_name.get(("epg2",norm(candidate)),set())
     if len(matches)==1:
      chosen=("epg2",next(iter(matches)),"espn_slot_name");break
   # No EPG2 match means a placeholder, never a different provider's schedule.
   decisions[sid]=chosen
   if chosen:
    wanted["epg2"].add(chosen[1])
    match_counts["epg2_"+chosen[2]]+=1
   continue
  # NCAAB slots 26-35 were omitted from the static JSON map.
  # Resolve their EPG 2 dummy source dynamically against the actual catalog,
  # using the original Xtream channel number and preserving its StreamID.
  if not chosen and "NCAAB" in group:
   slot_match=re.search(r"\bNCAAB(?:\s+GAME)?\s*0*(\d{1,2})\b",raw,re.I)
   if slot_match and 26<=int(slot_match.group(1))<=35:
    slot_number=int(slot_match.group(1))
    candidate=f"dummy-{5506284+slot_number}"
    canonical=by_id.get(("epg2",candidate.lower()))
    if canonical:
     chosen=("epg2",canonical,"ncaab_slot_26_35")
    else:
     matches=set()
     for label in (f"NCAAB {slot_number:02d}",f"NCAAB {slot_number}"):
      matches.update(by_name.get(("epg2",norm(label)),set()))
     if len(matches)==1:chosen=("epg2",next(iter(matches)),"ncaab_slot_name_26_35")
  for src,cid in preferred:
   canonical=by_id.get((src,cid.lower()))
   if canonical and not chosen:
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
def nba_from_inventory(rows):
 # Use Xtream StreamID as the only output identity. Match team feeds
 # to original NBA GAME slot matchup, never to generic EPG IDs.
 games=[]
 teams={}
 for row in rows:
  if val(row,"Group").upper()!="AM | USA | NBA":continue
  sid=val(row,"StreamID")
  raw=val(row,"OriginalChannelName","ChannelName")
  m=re.search(r"NBA GAME\s*(\d+)\s*:\s*(.*?)\s+@\s+(.*?)(?:\s*\(|\s+NOV\s+\d+|$)",raw,re.I)
  if m:
   try:
    d=re.search(r"\bNOV\s+(\d+)\s*[–-]\s*(\d{1,2}):(\d{2})\s*(AM|PM)\s*ET",raw,re.I)
    if not d:continue
    day,hour,minute,ap=d.groups()
    hour=int(hour)%12+(12 if ap.upper()=="PM" else 0)
    # Original Xtream labels are Eastern; November is EST after DST ends.
    eastern=timezone(timedelta(hours=-5))
    st=datetime(datetime.now(eastern).year,11,int(day),hour,int(minute),tzinfo=eastern).astimezone(timezone.utc)
    away=m.group(2).strip().upper()
    home=m.group(3).strip().upper()
    games.append((sid,st,st+timedelta(hours=4),away,home,int(m.group(1))))
   except ValueError:continue
  elif "NBA TEAMS -" in raw.upper():
   team=re.sub(r"\s+(?:FHD|HD|SD|4K)\b.*$","",raw.split("NBA TEAMS -",1)[-1],flags=re.I).strip().upper()
   teams[sid]=team
 return games,teams
def add_nba(tv,cid,sid,now,games,teams):
 horizon=now+timedelta(days=7)
 if sid in teams:
  team=teams[sid]
  relevant=sorted([g for g in games if team in (g[3],g[4]) and g[2]>now and g[1]<horizon],key=lambda g:g[1])
  cursor=now
  n=0
  for _,st,en,away,home,_ in relevant:
   if st>cursor:
    add_programme(tv,cid,cursor,st,"Next Game: "+away.title()+" @ "+home.title()+" ("+st.astimezone(timezone(timedelta(hours=-5))).strftime("%b %d, %I:%M %p EST")+")");n+=1
   add_programme(tv,cid,max(st,cursor),en,away.title()+" @ "+home.title());n+=1
   cursor=max(cursor,en)
  if cursor<horizon:
   add_programme(tv,cid,cursor,horizon,"Event concluded" if relevant else "No Game Scheduled");n+=1
  return n
 for gameid,st,en,away,home,num in games:
  if gameid==sid:
   if st>now:add_programme(tv,cid,now,st,"Next Game: "+away.title()+" @ "+home.title());n=1
   else:n=0
   if en>now:add_programme(tv,cid,max(st,now),en,away.title()+" @ "+home.title(),st.astimezone(timezone(timedelta(hours=-5))).strftime("%b %d, %I:%M %p EST"));n+=1
   if en<horizon:add_programme(tv,cid,max(now,en),horizon,"Event concluded");n+=1
   return n
 return 0
def generate():
 rows,inventory_source=find_inventory()
 rows=[r for r in rows if val(r,"StreamID") and in_scope(r)]
 if len(rows)<1000:raise RuntimeError(f"Inventory only has {len(rows)} scoped channels, refusing incomplete V4 publication")
 print("Inventory",inventory_source,"channels",len(rows),flush=True)
 overrides=load_overrides()
 programmes,decisions,match_counts=load_epgs(rows,overrides)
 ahl=ahl_schedule()
 nba_games,nba_teams=nba_from_inventory(rows)
 tv=ET.Element("tv",{"generator-info-name":"My-EPG V4 full inventory"})
 now=datetime.now(timezone.utc)
 start=now.strftime("%Y%m%d%H%M%S +0000")
 end=(now+timedelta(days=1)).strftime("%Y%m%d%H%M%S +0000")
 counts={"inventory_source":inventory_source,"channels":0,"programmes":0,"fallback_channels":0,"mapped_channels":0,"categories":{},"source_matches":match_counts,"scheduled_by_source":{},"unmatched_by_category":{}}
 seen=set()
 output_ids=set()
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
  if cid in output_ids:
   raise RuntimeError(f"Duplicate XMLTV channel ID {cid}; refusing ambiguous mapping")
  output_ids.add(cid)
  ch=ET.SubElement(tv,"channel",id=cid)
  ET.SubElement(ch,"display-name").text=title
  ET.SubElement(ch,"display-name").text=clean(name)
  events=programmes.get((source,epgid),[]) if selected else []
  if group.upper()=="AM | USA | NBA" and (sid in nba_teams or any(g[0]==sid for g in nba_games)):
   n=add_nba(tv,cid,sid,now,nba_games,nba_teams)
   counts["mapped_channels"]+=1
   counts["programmes"]+=n
   counts["scheduled_by_source"]["nba-xtream-streamid"]=counts["scheduled_by_source"].get("nba-xtream-streamid",0)+1
  elif "AHL" in group.upper() and sid in ahl:
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
   is_espn_slot = "ESPN PLUS" in group.upper() and cid.startswith(("ESPNPlus.", "ESPN.PLUS."))
   ET.SubElement(p,"title",lang="en").text="No Scheduled Event" if is_espn_slot else title
   ET.SubElement(p,"desc",lang="en").text="No verified ESPN+ event currently scheduled" if is_espn_slot else "V4: no verified schedule available; channel retained for later correction"
   counts["fallback_channels"]+=1
   counts["unmatched_by_category"][group]=counts["unmatched_by_category"].get(group,0)+1
  counts["channels"]+=1
 OUT.mkdir(parents=True,exist_ok=True)
 with gzip.open(OUT/"epg.xml.gz","wb",compresslevel=6) as f:
  f.write(ET.tostring(tv,encoding="utf-8",xml_declaration=True))
 # Direct EPG2 NCAAB test guide: one distinct channel ID per slot 01-38.
 # The published main V4 guide and provider inventory are unchanged.
 test_tv=copy.deepcopy(tv)
 ncaab_slots={}
 for row in rows:
  group=val(row,"Group").upper()
  raw=val(row,"OriginalChannelName","ChannelName","NewChannelName")
  match=re.search(r"\\bNCAAB(?:\\s+GAME)?\\s*0*(\\d{1,2})\\b",raw,re.I)
  if not match or "NCAAB" not in group:continue
  slot=int(match.group(1))
  if 1<=slot<=38:
   old="v4."+val(row,"StreamID")
   if slot in ncaab_slots and ncaab_slots[slot]!=old:
    raise RuntimeError(f"Multiple Xtream streams for NCAAB slot {slot}")
   ncaab_slots[slot]=old
 # The explicit mapping file covers slots with provider stream IDs.
 mapping_file=MAPPINGS/"ncaa-basketball.json"
 if mapping_file.exists():
  for item in json.loads(mapping_file.read_text(encoding="utf-8")).get("mappings",[]):
   match=re.search(r"NCAAB Game (\\d+)",str(item.get("channel","")),re.I)
   if match and 1<=int(match.group(1))<=38:
    slot=int(match.group(1))
    old="v4."+str(item.get("xtream_stream_id","")).strip()
    if old!="v4." and old in output_ids:ncaab_slots[slot]=old
 remap={old:f"NCAAB.{slot:02d}" for slot,old in ncaab_slots.items()}
 if len(remap)!=len(ncaab_slots):raise RuntimeError("NCAAB slot stream collision")
 for ch in test_tv.findall("channel"):
  old=ch.get("id")
  if old in remap:ch.set("id",remap[old])
 for p in test_tv.findall("programme"):
  old=p.get("channel")
  if old in remap:test_tv.remove(p)
  elif old in remap.values():test_tv.remove(p)
 # Slots missing from Xtream still receive guide-only channel definitions;
 # these do NOT invent Xtream streams.
 existing={ch.get("id") for ch in test_tv.findall("channel")}
 for slot in range(1,39):
  cid=f"NCAAB.{slot:02d}"
  if cid not in existing:
   ch=ET.SubElement(test_tv,"channel",id=cid)
   ET.SubElement(ch,"display-name").text=f"NCAAB Game {slot:02d}"
 # Transfer actual EPG2 programme start/stop/title/description directly,
 # without fabricated four-hour blocks or inferred EST times.
 epg2_data=request(SOURCES["epg2"])
 if epg2_data[:2]==b"\x1f\x8b":epg2_data=gzip.decompress(epg2_data)
 if not epg2_data.lstrip().startswith((b"<?xml",b"<tv",b"<!DOCTYPE")):
  raise RuntimeError("EPG2 download is not XML after decompression")
 # Match NFL/NCAAB pattern: keep the Xtream stream-based XMLTV channel IDs,
 # then copy actual EPG2 programme elements to those IDs.
 espn_dest={}
 espn_slots={}
 espn_names={}
 espn_old_to_new={}
 for row in rows:
  group=val(row,"Group").upper()
  raw=val(row,"OriginalChannelName","ChannelName","NewChannelName")
  m=re.search(r"ESPN\s*(?:\+|PLUS)\s*0*(\d{1,3})\b",raw,re.I)
  provider=re.fullmatch(r"ESPN(?:\.PLUS|Plus)\.(\d{1,3})",val(row,"EPGID","ProviderID"),re.I)
  slot=int(m.group(1)) if m else (int(provider.group(1)) if provider else 0)
  if not (1<=slot<=600 and ("ESPN PLUS" in group or provider)):continue
  cid="v4."+val(row,"StreamID")
  if slot in espn_slots and espn_slots[slot]!=cid:
   raise RuntimeError(f"Duplicate ESPN+ slot {slot}")
  new_cid=f"ESPNPlus.{slot}"
  espn_slots[slot]=new_cid
  espn_old_to_new[cid]=new_cid
  # Keep the exact original Xtream channel name as the guide display name.
  espn_names[new_cid]=val(row,"OriginalChannelName","ChannelName","NewChannelName") or f"ESPN+ {slot:03d}"
  if slot<=500:
   # EPG2 ESPN+ sources are sequential across both blocks:
   # 001-050 => dummy-3345444..3345493
   # 051-500 => dummy-3345494..3345943
   source_num=(3345444+slot-1) if slot<=50 else (3345494+slot-51)
   source_id=f"dummy-{source_num}"
   if source_id in espn_dest and espn_dest[source_id]!=new_cid:
    raise RuntimeError(f"ESPN+ source collision {source_id}")
   espn_dest[source_id]=new_cid
 # Fail fast if an ESPN+ source points at the wrong destination.
 for check_slot,check_source in ((1,"dummy-3345444"),(50,"dummy-3345493"),(51,"dummy-3345494"),(430,"dummy-3345873"),(500,"dummy-3345943")):
  if check_slot in espn_slots and espn_dest.get(check_source)!=f"ESPNPlus.{check_slot}":
   raise RuntimeError(f"ESPN+ mapping error: {check_source} should be ESPNPlus.{check_slot}")
 print("ESPN+ EPG2 mapping verified",len(espn_dest),"unique sources",flush=True)
 # Rename ESPN+ channel IDs in this test guide only, as with NFL/NCAAB.
 for ch in test_tv.findall("channel"):
  old=ch.get("id")
  if old in espn_old_to_new:ch.set("id",espn_old_to_new[old])
 # Align test-guide channel display names with the Xtream inventory, not
 # the dated event labels from EPG2 or generic slot placeholders.
 for ch in test_tv.findall("channel"):
  cid=ch.get("id")
  if cid in espn_names:
   for label in list(ch.findall("display-name")):ch.remove(label)
   ET.SubElement(ch,"display-name").text=espn_names[cid]
 # Replace only ESPN+ programmes in the test guide.
 espn_ids=set(espn_slots.values())
 for p in list(test_tv.findall("programme")):
  if p.get("channel") in espn_ids or p.get("channel") in espn_old_to_new:test_tv.remove(p)
 espn_counts=defaultdict(int)
 espn_found=set()
 for _,item in ET.iterparse(io.BytesIO(epg2_data),events=("end",)):
  if item.tag=="channel":
   if item.get("id") in espn_dest:espn_found.add(item.get("id"))
   item.clear()
  elif item.tag=="programme":
   cid=espn_dest.get(item.get("channel"))
   if cid:
    p=copy.deepcopy(item);p.set("channel",cid)
    test_tv.append(p);espn_counts[cid]+=1
   item.clear()
 for slot,cid in espn_slots.items():
  if slot>=501 or (slot<=500 and not espn_counts[cid]):
   p=ET.SubElement(test_tv,"programme",start=start,stop=end,channel=cid)
   ET.SubElement(p,"title",lang="en").text="No Programming"
   ET.SubElement(p,"desc",lang="en").text="No Programming"
 print("ESPN+ test",len(espn_slots),"Xtream slots",len(espn_found),"EPG2 sources",sum(espn_counts.values()),"programmes",flush=True)

 source_to_slot={f"dummy-{5506284+slot}":f"NCAAB.{slot:02d}" for slot in range(1,39)}
 imported=defaultdict(int)
 for _,item in ET.iterparse(io.BytesIO(epg2_data),events=("end",)):
  if item.tag=="programme":
   cid=source_to_slot.get(item.get("channel"))
   if cid:
    p=copy.deepcopy(item);p.set("channel",cid)
    test_tv.append(p);imported[cid]+=1
   item.clear()
  elif item.tag=="channel":item.clear()
 # NFL additions to the SAME test file. Never change the regular V4 guide.
 # Resolve real EPG2 IDs from the downloaded channel catalog; never assume
 # dummy numbering or substitute EPG37 for numbered games / networks.
 nfl_source_channels={}
 for _,item in ET.iterparse(io.BytesIO(epg2_data),events=("end",)):
  if item.tag=="channel":
   source_id=item.get("id")
   if source_id:
    nfl_source_channels[source_id]=[(d.text or "").strip() for d in item.findall("display-name")]
   item.clear()
  elif item.tag=="programme":item.clear()
 def nfl_epg2_id(target,aliases):
  wanted_names={norm(x) for x in aliases}
  matches=[]
  for source_id,names in nfl_source_channels.items():
   if norm(source_id) in wanted_names or any(norm(n) in wanted_names for n in names):
    matches.append(source_id)
  if len(matches)==1:return matches[0]
  print("NFL EPG2 source unresolved",target,"matches",matches[:12],flush=True)
  return None
 nfl_targets={}
 for slot in range(1,17):
  cid=f"NFL.GAME.{slot:02d}"
  # Verified user-selected EPG2 source: dummy-25609 through dummy-25624.
  # Keep NFL.GAME.XX as the destination ID; copy EPG2 programmes unchanged.
  source_id=f"dummy-{25608+slot}"
  if source_id not in nfl_source_channels:
   raise RuntimeError(f"Missing required EPG2 NFL source {source_id} for {cid}")
  nfl_targets[cid]=source_id
 for cid,aliases in {
  "nflredzone.us":["NFL RedZone","NFL Red Zone","NFLRedZone.us","nflredzone.us"],
  "nflnetwork.us":["NFL Network","NFLNetwork.us","nflnetwork.us"],
 }.items():
  nfl_targets[cid]=nfl_epg2_id(cid,aliases)
 # NFL Replay channels have blank original Xtream EPGIDs.
 # Retain their existing V4 stream-based IDs.
 replay_sources={"v4.1329644":"dummy-25627"}
 replay_sources.update({f"v4.{1329644+slot}":f"dummy-{25627+slot}" for slot in range(1,15)})
 for cid,source_id in replay_sources.items():
  if source_id not in nfl_source_channels:
   raise RuntimeError(f"Missing required EPG2 NFL replay source {source_id} for {cid}")
  nfl_targets[cid]=source_id
 # Preserve the known Xtream StreamIDs; only XMLTV identities change.
 nfl_stream_ids={f"NFL.GAME.{slot:02d}":str(79449+slot) for slot in range(1,17)}
 nfl_stream_ids.update({"nflredzone.us":"71984","nflnetwork.us":"71983"})
 nfl_old_to_new={"v4."+sid:cid for cid,sid in nfl_stream_ids.items()}
 nfl_existing={ch.get("id") for ch in test_tv.findall("channel")}
 for ch in test_tv.findall("channel"):
  old=ch.get("id")
  if old in nfl_old_to_new:ch.set("id",nfl_old_to_new[old])
 for p in list(test_tv.findall("programme")):
  if p.get("channel") in nfl_old_to_new or p.get("channel") in replay_sources:test_tv.remove(p)
 for cid in nfl_targets:
  if cid not in {ch.get("id") for ch in test_tv.findall("channel")}:
   ch=ET.SubElement(test_tv,"channel",id=cid)
   ET.SubElement(ch,"display-name").text=cid
 # Import only matched real EPG2 programme records, preserving timestamps.
 nfl_by_source=defaultdict(list)
 for cid,source_id in nfl_targets.items():
  if source_id:nfl_by_source[source_id].append(cid)
 nfl_counts=defaultdict(int)
 for _,item in ET.iterparse(io.BytesIO(epg2_data),events=("end",)):
  if item.tag=="programme":
   for cid in nfl_by_source.get(item.get("channel"),[]):
    p=copy.deepcopy(item);p.set("channel",cid)
    test_tv.append(p);nfl_counts[cid]+=1
   item.clear()
  elif item.tag=="channel":item.clear()
 # NFL team channels are deliberately left as V4's existing EPG37 mappings.
 print("NFL test EPG2",len([v for v in nfl_targets.values() if v]),
       "of",len(nfl_targets),"resolved",sum(nfl_counts.values()),"programmes",flush=True)
 test_ids=[ch.get("id") for ch in test_tv.findall("channel")]
 if len(test_ids)!=len(set(test_ids)):raise RuntimeError("Duplicate IDs in NCAAB test guide")
 print("NCAAB EPG2 direct 01-38",len(ncaab_slots),"inventory slots",sum(imported.values()),"source programmes",flush=True)
 with gzip.open(OUT/"ncaab-original-id-test.xml.gz","wb",compresslevel=6) as f:
  f.write(ET.tostring(test_tv,encoding="utf-8",xml_declaration=True))
 print("NCAAB direct EPG2 test generated",len(ncaab_slots),"inventory slots",sum(imported.values()),"programme entries",flush=True)
 (OUT/"coverage.json").write_text(json.dumps(counts,indent=2),encoding="utf-8")
 print("V4 generated",json.dumps({k:v for k,v in counts.items() if k!="categories"}),flush=True)
if __name__=="__main__":generate()
