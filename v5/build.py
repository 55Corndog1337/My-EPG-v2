#!/usr/bin/env python3
"""Isolated V5 test XMLTV build. Never writes V4 or V2 outputs."""
import csv,gzip,io,json,os,pathlib,re,urllib.request,xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime,timedelta,timezone
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/"v5-output"
OUT.mkdir(exist_ok=True)
SOURCES={"epg2":"https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg2.xml.gz","epg37":"https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg37.xml.gz","epg6":"https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg6.xml.gz"}
def fetch(url):
 h={"User-Agent":"V5-test-EPG/1"}
 token=os.getenv("GITHUB_TOKEN","")
 if token and "api.github.com" in url:h["Authorization"]="Bearer "+token
 with urllib.request.urlopen(urllib.request.Request(url,headers=h),timeout=120) as r:return r.read()
def value(row,*keys):
 d={str(k).lower().replace(" ","").strip():str(v or "").strip() for k,v in row.items() if k}
 return next((d[k.lower().replace(" ","")] for k in keys if d.get(k.lower().replace(" ",""))),"")
def inventory():
 paths=[ROOT/"v5-input"/"inventory.csv",ROOT/"v4-input"/"sports-renamed"/"ALL_CHANNELS_Renamed.csv",ROOT/"v4-input"/"ALL_CHANNELS_Renamed.csv",ROOT/"v4"/"inventory.csv"]
 for p in paths:
  if p.exists() and p.stat().st_size:
   rows=list(csv.DictReader(p.open(encoding="utf-8-sig",newline="")))
   if len(rows)>100:return rows,str(p)
 # Retrieve most recent inventory artifact from Actions, without changing V4.
 repo=os.getenv("GITHUB_REPOSITORY","55Corndog1337/My-EPG-v2")
 try:
  import zipfile
  payload=json.loads(fetch(f"https://api.github.com/repos/{repo}/actions/artifacts?per_page=100"))
  for a in sorted((x for x in payload.get("artifacts",[]) if not x.get("expired")),key=lambda x:x.get("created_at",""),reverse=True):
   if not any(k in a.get("name","").lower() for k in ("inventory","matching","xtream","channel")):continue
   try:
    z=zipfile.ZipFile(io.BytesIO(fetch(a["archive_download_url"])))
    for name in z.namelist():
     if name.lower().endswith(".csv") and any(k in name.lower() for k in ("all_channels","inventory","xtream")):
      rows=list(csv.DictReader(io.StringIO(z.read(name).decode("utf-8-sig"))))
      if len(rows)>100 and value(rows[0],"StreamID"):return rows,"artifact:"+a["name"]
   except Exception as e:print("Artifact skipped",str(e)[:100])
 except Exception as e:print("Inventory lookup:",e)
 raise RuntimeError("No full Xtream inventory found. V5 test output not published.")
def normalize(s):
 s=re.sub(r"^(?:US|USA|UK|CA|VIP)\s*[-|:]\s*","",s,flags=re.I)
 s=re.sub(r"\b(?:UHD|FHD|HD|SD|4K|HEVC)\b","",s,flags=re.I)
 s=re.sub(r"\\b(?:EASTERN|EAST|WESTERN|WEST|BACKUP|BK)\\b","",s,flags=re.I)
 return re.sub(r"[^a-z0-9]","",s.lower())
def source_for(name,group):
 text=name+" "+group
 # Team-specific feeds are sourced from EPG 37.
 if re.search(r"\b(?:NFL|NHL|NBA|MLB)\b",text,re.I) and not re.search(r"\b(?:GAME|REPLAY|HIGHLIGHTS|PPV|IN THE ARENA)\s*0*\d+\b",text,re.I):
  if not re.search(r"\b(?:NETWORK|REDZONE|STRIKEZONE|TV|ARENA)\b",text,re.I):return "epg37"
 if re.search(r"\b(?:ESPN\s*(?:\+|PLUS)|FLO\s*SPORTS|NCAAB|NCAAF|NFL|NHL|NBA|MLB|MILB|MLS|WNBA|PEACOCK|PARAMOUNT|TSN\+|BTN\+|B1G\+|MAX\s*PPV|DISNEY\s*PLUS)\b",text,re.I):return "epg2"
 return None
RULES=[
 (r"ESPN\s*(?:\+|PLUS)\s*0*(\d{1,3})\b",1,500,3345443),
 (r"FLO\s*SPORTS\s*0*(\d{1,3})\b",1,800,3769824),
 (r"NCAAB\s*(?:GAME\s*)?0*(\d{1,3})\b",1,101,5506284),
 (r"NCAAF\s*(?:GAME\s*)?0*(\d{1,3})\b",1,85,26365),
 (r"NFL\s*GAME\s*0*(\d{1,2})\b",1,16,25608),
 (r"NBA\s*GAME\s*0*(\d{1,2})\b",1,15,4476727),
 (r"PEACOCK\s*0*(\d{1,3})\b",1,100,4817577),
 (r"PARAMOUNT\s*\+?\s*0*(\d{1,3})\b",1,100,1405346),
 (r"TSN\s*\+\s*0*(\d{1,3})\b",1,150,3782013),
 (r"(?:BTN\+|B1G\+)\s*0*(\d{1,3})\b",1,150,6174566),
 (r"MAX\s*PPV\s*0*(\d{1,2})\b",1,40,26519),
 (r"MLS\s*(?:GAME\s*)?0*(\d{1,2})\b",1,20,1280664),
 (r"WNBA\s*(?:GAME\s*)?0*(\d{1,2})\b",1,10,2003813),
]
def run():
 rows,invsource=inventory()
 catalogs={};programmes=defaultdict(list);byname=defaultdict(set)
 for source,url in SOURCES.items():
  blob=fetch(url)
  if blob[:2]==b"\x1f\x8b":blob=gzip.decompress(blob)
  channels={}
  for event,item in ET.iterparse(io.BytesIO(blob),events=("end",)):
   if item.tag=="channel":
    cid=item.get("id")
    if cid:
     names=[x.text or "" for x in item.findall("display-name")]
     channels[cid]=names
     for n in names:byname[source,normalize(n)].add(cid)
    item.clear()
   elif item.tag=="programme":
    cid=item.get("channel")
    if cid:programmes[source,cid].append(ET.tostring(item,encoding="unicode"))
    item.clear()
  catalogs[source]=channels
  print(source,len(channels),flush=True)
 root=ET.Element("tv",{"generator-info-name":"My-EPG V5 test"})
 report=[];matched=0
 for row in rows:
  sid=value(row,"StreamID")
  if not sid:continue
  name=value(row,"OriginalChannelName","ChannelName","NewChannelName","Original Xtream Name")
  group=value(row,"Group")
  if not any(k in group.upper() for k in ("UK","US","CA","VIP","CHRISTMAS")):continue
  src=source_for(name,group)
  if re.search(r"\bAHL\b",name+" "+group,re.I):src="generated-ahl"
  candidates=[]
  if src=="epg2":
   for pat,lo,hi,base in RULES:
    m=re.search(pat,name,re.I)
    if m and lo<=int(m.group(1))<=hi:
     candidates.append("dummy-"+str(base+int(m.group(1))))
     break
   d=re.search(r"DISNEY\s*(?:\+|PLUS)\s*0*(\d{1,2})\b",name,re.I)
   if d:
    n=int(d.group(1))
    if 1<=n<=5:candidates.append("dummy-"+str(124278+n))
    elif 6<=n<=15:candidates.append("dummy-"+str(3184719+n))
  if src in catalogs:
   old=value(row,"EPGID","ProviderID")
   if old:candidates.append(old)
   candidates.extend(sorted(byname.get((src,normalize(name)),set())))
  # Regular TV: prefer an existing source ID; otherwise require a unique name.
  if not src:
   old=value(row,"EPGID","ProviderID")
   for candidate_source in ("epg37","epg2","epg6"):
    if old and old in catalogs[candidate_source]:
     src=candidate_source;candidates=[old];break
   if not src:
    for candidate_source in ("epg37","epg2","epg6"):
     ids=byname.get((candidate_source,normalize(name)),set())
     if len(ids)==1:
      src=candidate_source;candidates=list(ids);break
  chosen=next((x for x in candidates if x in catalogs.get(src,{})),None)
  if chosen:
   channel=ET.SubElement(root,"channel",id="v5."+sid)
   ET.SubElement(channel,"display-name").text=name or sid
   for xml in programmes.get((src,chosen),[]):
    item=ET.fromstring(xml);item.set("channel","v5."+sid);root.append(item)
   matched+=1
  report.append([sid,name,group,src or "",chosen or "", "matched" if chosen else "unmatched"])
 if matched==0:raise RuntimeError("No valid V5 matches; refusing to publish an empty guide")
 with (OUT/"mapping-report.csv").open("w",encoding="utf-8",newline="") as f:
  w=csv.writer(f);w.writerow(["StreamID","Original Name","Group","Source","Source ID","Status"]);w.writerows(report)
 with gzip.open(OUT/"epg.xml.gz","wb",compresslevel=6) as f:f.write(ET.tostring(root,encoding="utf-8",xml_declaration=True))
 print("V5 TEST",len(report),"channels,",matched,"mapped; inventory:",invsource)
if __name__=="__main__":run()
