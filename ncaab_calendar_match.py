#!/usr/bin/env python3
"""Match numbered Xtream NCAAB channels to same-number EPG2, then validate against ICS."""
import gzip,json,re,urllib.request,xml.etree.ElementTree as ET
from datetime import datetime,timezone,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent
EAST=ZoneInfo("America/New_York")
EPG2="https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg2.xml.gz"
D2_SOURCE="https://d2hoopstoo.com/schedule"
NUMBERS=tuple(range(1,26))+(36,37,38)
def norm(s):
 return re.sub(r"[^a-z0-9]+"," ",re.sub(r"\b(?:ranked|no|number)\b","",s.lower())).strip()
def teams(title):
 title=re.sub(r"^.*?\bNCAAB\s*0*\d+\s*[:|\-]\s*","",title,flags=re.I)
 title=re.sub(r"\s*\([^)]*\)\s*$","",title)
 m=re.search(r"(.+?)\s+(?:@|vs\.?|versus)\s+(.+)",title,re.I)
 if not m:return None
 a,b=norm(m.group(1)),norm(m.group(2))
 return (a,b) if a and b else None
def load():
 req=urllib.request.Request(EPG2,headers={"User-Agent":"MyEPG/2.0"})
 with urllib.request.urlopen(req,timeout=45) as f:data=f.read(40000001)
 if len(data)>40000000:raise ValueError("EPG2 too large")
 if data[:2]==b"\x1f\x8b":data=gzip.decompress(data)
 return ET.fromstring(data)
def run():
 from schedule_sources import refresh,CACHE
 if not CACHE.exists():refresh()
 calendar=json.loads(CACHE.read_text(encoding="utf-8")).get("sources",{}).get("college-basketball",[])
 root=load()
 ids={}
 for c in root.findall("channel"):
  cid=c.get("id","")
  names=[cid]+[x.text or "" for x in c.findall("display-name")]
  for n in names:
   m=re.search(r"\bNCAAB\s*0*(\d{1,2})\b",n,re.I)
   if m:
    k=int(m.group(1))
    if k in NUMBERS:ids.setdefault(k,set()).add(cid)
 events={}
 for e in calendar:
  pair=teams(e.get("event",""))
  try:start=datetime.fromisoformat(e["start_utc"]).astimezone(EAST)
  except (ValueError,KeyError):continue
  if pair:events.setdefault(tuple(sorted(pair)),[]).append((start,e))
 now=datetime.now(EAST)
 programmes_by_id={}
 for p in root.findall("programme"):
  programmes_by_id.setdefault(p.get("channel"),[]).append(p)
 rows=[]
 for num in NUMBERS:
  cidset=ids.get(num,set())
  ps=[p for cid in cidset for p in programmes_by_id.get(cid,[])]
  raw=[{"epg2_channel":p.get("channel"),"title":p.findtext("title",""),"start":p.get("start"),"stop":p.get("stop"),"description":p.findtext("desc","")} for p in ps]
  found=[]
  for p in ps:
   title=p.findtext("title","")
   pair=teams(title)
   if not pair:continue
   for start,event in events.get(tuple(sorted(pair)),[]):
    if start.date()!=now.date():continue
    found.append({"title":title,"start":start.isoformat(),"calendar_title":event["event"],"epg2_channel":p.get("channel")})
  unique={(x["title"],x["start"]):x for x in found}
  rows.append({"xtream_channel":"NCAAB %02d"%num,"epg2_ids":sorted(cidset),"status":"matched" if len(unique)==1 else ("ambiguous" if unique else "unmatched"),"epg2_programmes":raw,"matches":list(unique.values())})
 out=ROOT/"reports"/("ncaab-calendar-match-"+now.strftime("%Y-%m-%d")+".json")
 out.parent.mkdir(exist_ok=True)
 out.write_text(json.dumps({"date":str(now.date()),"method":"same-number EPG2 channel then exact team-pair ICS match","source_urls":{"epg2":EPG2,"college_basketball_ics":"https://www.collegebasketballschedule.net/calendar/feed.ics","d2_men_schedule":D2_SOURCE},"d2_note":"D2HoopsToo is a supplemental schedule verification source. Its future months load dynamically; no D2 event is claimed verified unless explicitly extracted.","channels":rows},indent=2)+"\n")
 print("NCAAB match report:",out,"matched:",sum(x["status"]=="matched" for x in rows))
if __name__=="__main__":run()
