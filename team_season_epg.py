#!/usr/bin/env python3
"""Weekly season schedule snapshots for team-channel XMLTV. No paid API."""
import json, re, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parent
SNAPSHOT=ROOT/"reports"/"team-seasons.json"
EASTERN=ZoneInfo("America/New_York")
LEAGUES={
 "NFL":("football","nfl",2026,8,2027,3,3),
 "NBA":("basketball","nba",2026,9,2027,7,4),
 "NHL":("hockey","nhl",2026,9,2027,7,4),
 "MLB":("baseball","mlb",2026,2,2027,1,4),
 "WNBA":("basketball","wnba",2026,4,2027,1,4),
 "MLS":("soccer","usa.1",2026,1,2027,1,4),
}
def norm(s):
 return re.sub(r"[^a-z0-9]","",s.lower())
def fetch(league, start, end):
 sport, code, *_=LEAGUES[league]
 url=f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{code}/scoreboard?dates={start:%Y%m%d}-{end:%Y%m%d}&limit=1000"
 req=urllib.request.Request(url,headers={"User-Agent":"My-EPG-v2/1.0"})
 with urllib.request.urlopen(req,timeout=65) as response:
  return json.load(response).get("events",[])
def refresh():
 old={}
 if SNAPSHOT.exists():
  try: old=json.loads(SNAPSHOT.read_text())
  except (ValueError,OSError): pass
 result={"generated":datetime.now(timezone.utc).isoformat(),"leagues":{}}
 for league,(sport,code,sy,sm,ey,em,hours) in LEAGUES.items():
  # Split full seasons into month-sized requests to avoid truncating game lists.
  cursor=datetime(sy,sm,1,tzinfo=timezone.utc)
  finish=datetime(ey,em,1,tzinfo=timezone.utc)
  found={}
  errors=[]
  while cursor<finish:
   nxt=(cursor.replace(day=28)+timedelta(days=4)).replace(day=1)
   try:
    for event in fetch(league,cursor,min(nxt,finish)-timedelta(days=1)):
     competitors=(event.get("competitions") or [{}])[0].get("competitors") or []
     away=next((x for x in competitors if x.get("homeAway")=="away"),None)
     home=next((x for x in competitors if x.get("homeAway")=="home"),None)
     if not away or not home: continue
     a=away.get("team") or {}; h=home.get("team") or {}
     start=datetime.fromisoformat(event["date"].replace("Z","+00:00"))
     if start.tzinfo is None: continue
     game={"away":a.get("displayName",""),"home":h.get("displayName",""),
           "away_abbr":a.get("abbreviation",""),"home_abbr":h.get("abbreviation",""),
           "start":start.astimezone(timezone.utc).isoformat(),"hours":hours}
     if game["away"] and game["home"]: found[str(event.get("id") or game["start"]+game["away"])]=game
   except Exception as exc: errors.append(f"{cursor:%Y-%m}: {type(exc).__name__}: {exc}")
   cursor=nxt
  if errors or not found:
   previous=(old.get("leagues") or {}).get(league) or []
   if previous:
    result["leagues"][league]=previous
    print(league,"retained previous season due to source errors:",errors[:2])
    continue
   raise RuntimeError(f"{league}: incomplete season and no previous snapshot: {errors[:2]}")
  result["leagues"][league]=sorted(found.values(),key=lambda x:x["start"])
  print(league,len(found),"season games")
 # AHL full season is already held in reports/ahl-season-2026-27.csv and consumed separately.
 SNAPSHOT.parent.mkdir(parents=True,exist_ok=True)
 SNAPSHOT.write_text(json.dumps(result,separators=(",",":")),encoding="utf-8")
 return result

def apply(catalog,channels,programmes,reports):
 if not SNAPSHOT.exists():
  print("Weekly team season snapshot absent; retaining existing sports guide")
  return programmes
 data=json.loads(SNAPSHOT.read_text()).get("leagues",{})
 now=datetime.now(timezone.utc); horizon=now+timedelta(days=7)
 replacements={}
 for row in catalog:
  name=(row.get("ChannelName") or "").strip()
  group=(row.get("Group") or "").upper()
  sid=(row.get("StreamID") or "").strip()
  if not sid or "####" in name: continue
  league=next((k for k in LEAGUES if re.search(r"\b"+k+r"\b",group+" "+name,re.I)),None)
  if not league or not re.search(r"TEAM",group+" "+name,re.I): continue
  team=re.sub(r"^.*?\bTEAMS?\b\s*[-:|]\s*","",name,flags=re.I)
  team=re.sub(r"\b(?:HD|FHD|UHD|4K|SD|USA|US|CA|VIP)\b","",team,flags=re.I).strip(" -:|")
  team_key=norm(team)
  if not team_key: continue
  games=[]
  for game in data.get(league,[]):
   aliases=[game["away"],game["home"]]
   if any(team_key==norm(x) or (len(team_key)>7 and (team_key in norm(x) or norm(x) in team_key)) for x in aliases):
    try:
     start=datetime.fromisoformat(game["start"])
     games.append((start,start+timedelta(hours=game["hours"]),game["away"]+" @ "+game["home"]))
    except (ValueError,KeyError): pass
  if not games: continue
  games.sort()
  ids=["xtream."+sid]
  provider=(row.get("EPGID") or "").strip()
  if provider and provider not in ids: ids.append(provider)
  for pid in ids:
   if pid not in channels:
    ch=ET.Element("channel",{"id":pid});ET.SubElement(ch,"display-name").text=team
    channels[pid]=ch
   cursor=now; entries=[]
   while cursor<horizon:
    active=next((g for g in games if g[0]<=cursor<g[1]),None)
    if active:
     start,end,event=active; stop=min(end,horizon)
     title=f"{event} ({start.astimezone(EASTERN):%B %d, %I:%M %p %Z})"
    else:
     future=next((g for g in games if g[0]>cursor),None)
     if future:
      start,end,event=future;stop=min(start,horizon)
      title=f"Next Game: {event} ({start.astimezone(EASTERN):%B %d, %I:%M %p %Z})"
     else:
      stop=horizon;title="No Game Scheduled"
    if stop<=cursor:break
    p=ET.Element("programme",{"channel":pid,"start":cursor.strftime("%Y%m%d%H%M%S +0000"),"stop":stop.strftime("%Y%m%d%H%M%S +0000")})
    ET.SubElement(p,"title",{"lang":"en"}).text=title
    entries.append(p);cursor=stop
   replacements[pid]=entries
 if replacements:
  programmes=[p for p in programmes if p.get("channel") not in replacements]
  for entries in replacements.values():programmes.extend(entries)
 print("Weekly season team channels mapped:",len(replacements))
 return programmes

if __name__=="__main__":
 refresh()
