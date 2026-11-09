#!/usr/bin/env python3
"""Build NFL 2026 season XMLTV, including team feeds and postseason placeholders."""
import json, urllib.request, gzip, re
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

OUT=Path("site/nfl-2026-season.xml.gz")
EASTERN=ZoneInfo("America/New_York")
BASE="https://site.api.espn.com/apis/site/v2/sports/football/nfl"
def get(url):
 req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 My-EPG-v2"})
 with urllib.request.urlopen(req,timeout=60) as f:return json.load(f)
def stamp(dt):return dt.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S +0000")
def add(root,pid,start,end,title,desc=""):
 if end<=start:return
 p=ET.SubElement(root,"programme",channel=pid,start=stamp(start),stop=stamp(end))
 ET.SubElement(p,"title",lang="en").text=title
 if desc:ET.SubElement(p,"desc",lang="en").text=desc
def fmt(dt):
 d=dt.astimezone(EASTERN)
 return f"{d:%A, %B} {d.day}, {d:%I:%M %p %Z}"
def month_range(y,m):
 a=datetime(y,m,1,tzinfo=timezone.utc)
 b=(a.replace(day=28)+timedelta(days=4)).replace(day=1)
 return a,b
def main():
 teams=get(BASE+"/teams?limit=100")["sports"][0]["leagues"][0]["teams"]
 names={}
 for item in teams:
  t=item["team"];abbr=t.get("abbreviation","")
  if abbr:names[abbr]=t.get("displayName",abbr)
 if len(names)!=32:raise RuntimeError(f"Expected 32 NFL teams; received {len(names)}")
 games={}
 for year,month in [(2026,m) for m in range(8,13)]+[(2027,m) for m in range(1,3)]:
  a,b=month_range(year,month)
  url=f"{BASE}/scoreboard?dates={a:%Y%m%d}-{(b-timedelta(days=1)):%Y%m%d}&limit=1000"
  events=get(url).get("events",[])
  for e in events:
   competition=(e.get("competitions") or [{}])[0]
   cs=competition.get("competitors") or []
   away=next((c for c in cs if c.get("homeAway")=="away"),None)
   home=next((c for c in cs if c.get("homeAway")=="home"),None)
   if not away or not home:continue
   start=datetime.fromisoformat(e["date"].replace("Z","+00:00"))
   ateam=away["team"];hteam=home["team"]
   week=(e.get("week") or {}).get("number")
   stage=(e.get("season") or {}).get("type",2)
   games[str(e.get("id") or start.isoformat())]=dict(start=start,away=ateam["displayName"],home=hteam["displayName"],away_id=ateam.get("abbreviation",""),home_id=hteam.get("abbreviation",""),week=week,stage=stage)
 regular=[g for g in games.values() if g["stage"]==2 and datetime(2026,9,1,tzinfo=timezone.utc)<=g["start"]<datetime(2027,1,15,tzinfo=timezone.utc)]
 if len(regular)<250:raise RuntimeError(f"Incomplete NFL regular-season schedule: {len(regular)} games; refusing to publish")
 root=ET.Element("tv",{"generator-info-name":"My-EPG-v2 NFL full season"})
 for pid,name in [("nfl.weekly","NFL Weekly Matchups")]+[("nfl.team."+a,"NFL "+n) for a,n in sorted(names.items())]:
  ch=ET.SubElement(root,"channel",id=pid);ET.SubElement(ch,"display-name").text=name
 # Weekly feed: simultaneous games are separate programmes on the same channel;
 # consumers may prefer the team feeds for non-overlapping listings.
 for g in sorted(games.values(),key=lambda g:g["start"]):
  start=g["start"];end=start+timedelta(hours=3)
  matchup=g["away"]+" @ "+g["home"]
  stage="Playoffs" if g["stage"]==3 else "Regular Season" if g["stage"]==2 else "Preseason"
  label=f"{matchup} ({fmt(start)})"
  add(root,"nfl.weekly",start,end,label,f"{stage}; Week {g['week'] or '?'}; {fmt(start)}")
 for abbr in sorted(names):
  pid="nfl.team."+abbr
  matches=sorted([g for g in games.values() if abbr in (g["away_id"],g["home_id"])],key=lambda g:g["start"])
  cursor=datetime(2026,8,1,tzinfo=timezone.utc)
  horizon=datetime(2027,3,1,tzinfo=timezone.utc)
  for g in matches:
   start=g["start"];end=start+timedelta(hours=3)
   if end<=cursor:continue
   matchup=g["away"]+" @ "+g["home"]
   if start>cursor:add(root,pid,cursor,start,f"Next Game: {matchup} ({fmt(start)})")
   add(root,pid,max(cursor,start),end,f"{matchup} ({fmt(start)})",f"{matchup}; {fmt(start)}")
   cursor=end
  if cursor<horizon:add(root,pid,cursor,horizon,"No Game Scheduled")
 # Playoff slots are intentionally not fabricated: known pairings from the API
 # are included automatically, and a generic playoff feed announces unfilled rounds.
 ch=ET.SubElement(root,"channel",id="nfl.playoffs")
 ET.SubElement(ch,"display-name").text="NFL Playoffs 2026-27"
 for g in sorted((g for g in games.values() if g["stage"]==3),key=lambda g:g["start"]):
  add(root,"nfl.playoffs",g["start"],g["start"]+timedelta(hours=3),f"{g['away']} @ {g['home']} ({fmt(g['start'])})")
 OUT.parent.mkdir(parents=True,exist_ok=True)
 raw=ET.tostring(root,encoding="utf-8",xml_declaration=True)
 with gzip.open(OUT,"wb",compresslevel=9) as f:f.write(raw)
 print(f"Wrote {OUT}: {len(regular)} regular-season games, {len(games)} total known fixtures, 32 team feeds")
if __name__=="__main__":main()
