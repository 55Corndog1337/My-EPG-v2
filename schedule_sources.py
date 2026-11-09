#!/usr/bin/env python3
"""Refresh independently sourced calendar events; never assign stale events to channels."""
import json,re,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent
CACHE=ROOT/"reports"/"schedule-source-events.json"
SOURCES={
 "fancalendar-college-football":"https://fancalendar.app/api/subscription/c4a572a8e9f39eb3.ics",
 "college-basketball":"https://www.collegebasketballschedule.net/calendar/feed.ics"}
PAGES={
 "flosports":"https://www.flosports.tv/schedule?date={date}",
 "espn-plus-live":"https://www.espn.com/watch/schedule/_/type/live/channel/ESPN_PLUS",
 "espn-plus-upcoming":"https://www.espn.com/watch/schedule/_/type/upcoming/channel/ESPN_PLUS"}
def fetch(url):
 req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; MyEPG/2.0)","Accept":"text/calendar,text/html,*/*"})
 with urllib.request.urlopen(req,timeout=35) as response:
  data=response.read(15000001)
  if len(data)>15000000:raise ValueError("oversized source")
  return data.decode("utf-8-sig","replace")
def parse_date(value,params):
 value=value.strip()
 if not re.fullmatch(r"\d{8}T(?:\d{4}|\d{6})Z?",value):return None
 fmt="%Y%m%dT%H%M%S" if len(value.rstrip("Z"))==15 else "%Y%m%dT%H%M"
 d=datetime.strptime(value.rstrip("Z"),fmt)
 if value.endswith("Z"):d=d.replace(tzinfo=timezone.utc)
 else:
  m=re.search(r"TZID=([^;:]+)",params,re.I)
  if not m:return None
  try:d=d.replace(tzinfo=ZoneInfo(m.group(1)))
  except Exception:return None
 return d.astimezone(timezone.utc).isoformat()
def parse_ics(body,source):
 if "BEGIN:VCALENDAR" not in body:return []
 events=[];item=None
 for line in re.sub(r"\r?\n[ \t]","",body).splitlines():
  if line=="BEGIN:VEVENT":item={};continue
  if line=="END:VEVENT" and item is not None:
   if item.get("start_utc") and item.get("event"):events.append(dict(item,source=source))
   item=None;continue
  if item is None or ":" not in line:continue
  key,value=line.split(":",1);field=key.split(";",1)[0].upper()
  value=value.replace("\\, ",", ").replace("\\,",",").replace("\\n"," ").replace("\\N"," ")
  if field=="DTSTART":item["start_utc"]=parse_date(value,key)
  elif field=="SUMMARY":item["event"]=value
  elif field in ("UID","URL","LOCATION"):item[field.lower()]=value
 return events
def refresh():
 try:previous=json.loads(CACHE.read_text(encoding="utf-8")).get("sources",{})
 except (OSError,ValueError,TypeError):previous={}
 sources={};status={}
 for name,url in SOURCES.items():
  try:
   events=parse_ics(fetch(url),name)
   if not events:raise ValueError("no timed events")
   sources[name]=events;status[name]={"state":"fresh","events":len(events)}
  except Exception as exc:
   sources[name]=previous.get(name,[])
   status[name]={"state":"cached" if sources[name] else "unavailable","events":len(sources[name]),"error":type(exc).__name__}
 for name,url in PAGES.items():
  try:
   page=fetch(url.format(date=datetime.now(ZoneInfo("America/New_York")).date().isoformat()))
   status[name]={"state":"accessible" if "<html" in page.lower() else "unrecognized","events":0}
  except Exception as exc:status[name]={"state":"unavailable","events":0,"error":type(exc).__name__}
 CACHE.parent.mkdir(exist_ok=True)
 CACHE.write_text(json.dumps({"updated_utc":datetime.now(timezone.utc).isoformat(),"sources":sources,"status":status},indent=2)+"\n",encoding="utf-8")
 for name,state in status.items():print("Schedule source:",name,state)
if __name__=="__main__":refresh()
