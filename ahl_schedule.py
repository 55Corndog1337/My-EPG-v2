"""Generate AHL team-channel XMLTV from the public HockeyTech league schedule."""
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

EASTERN = ZoneInfo("America/New_York")
BASE = "https://lscluster.hockeytech.com/feed/index.php"
KEY = "ccb91f29d6744675"

def _fetch(season):
    from urllib.parse import urlencode
    query = urlencode({"feed":"statviewfeed","view":"schedule","team":-1,
                       "season":season,"month":-1,"key":KEY,
                       "client_code":"ahl","league_id":4,"site_id":3,"lang":"en"})
    request = urllib.request.Request(BASE+"?"+query,headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(request,timeout=22) as response:
        raw=response.read(15000000).decode("utf-8-sig").strip()
    if not raw.startswith(("{","[")):
        raw=raw[raw.index("(")+1:raw.rfind(")")].strip()
    return json.loads(raw)

def _rows(node):
    if isinstance(node,dict):
        if isinstance(node.get("row"),dict):
            yield node["row"]
        for value in node.values():
            yield from _rows(value)
    elif isinstance(node,list):
        for value in node:
            yield from _rows(value)

def _value(row,*keys):
    for key in keys:
        value=row.get(key)
        if isinstance(value,dict):
            value=value.get("name") or value.get("value")
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""

def _datetime(row):
    value=_value(row,"date_with_time","game_date_iso_8601","date_played","date","game_date")
    time=_value(row,"scheduled_time","game_time","time","time_played")
    for raw in (value, value+" "+time):
        try:
            parsed=datetime.fromisoformat(raw.replace("Z","+00:00"))
            if parsed.tzinfo is None:
                parsed=parsed.replace(tzinfo=EASTERN)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    return None

def _norm(value):
    return re.sub(r"[^a-z0-9]","",value.lower())

def _programme(pid,title,start,stop):
    def stamp(dt):return dt.strftime("%Y%m%d%H%M%S +0000")
    p=ET.Element("programme",{"channel":pid,"start":stamp(start),"stop":stamp(stop)})
    ET.SubElement(p,"title",{"lang":"en"}).text=title
    return p

def run(catalog,channels,programmes,reports):
    now=datetime.now(timezone.utc)
    targets={}
    for row in catalog:
        name=(row.get("ChannelName") or "").strip()
        group=(row.get("Group") or "").upper()
        if "AHL" not in name.upper() and "AHL" not in group:
            continue
        if re.search(r"\b(?:GAME|REPLAY)\s*\d+\b",name,re.I):
            continue
        # Bind AHL team guide entries to their Xtream inventory StreamIDs,
        # regardless of stale or missing provider EPGIDs.
        stream=(row.get("StreamID") or "").strip()
        pid="xtream."+stream if stream else ""
        if pid:
            if pid not in channels:
                ch=ET.Element("channel",{"id":pid})
                ET.SubElement(ch,"display-name").text=name
                channels[pid]=ch
            team=re.sub(r"^(?:(?:US|USA|CA|VIP|AHL)\s*[-:|]\s*)+","",name,flags=re.I)
            team=re.sub(r"\b(?:AHL|HD|FHD|UHD|4K)\b"," ",team,flags=re.I).strip(" -:|")
            if team:
                targets[pid]=team
    if not targets:
        print("AHL generator: no mapped team channels")
        return programmes
    games={}
    # HockeyTech season IDs change annually; query adjacent seasons to avoid
    # hardcoding a single year. Only accept identifiable, dated matchups.
    for season in (90,91,89,92):
        try:
            for row in _rows(_fetch(season)):
                away=_value(row,"visiting_team_name","visitor_team_name","away_team_name","visiting_team","away_team")
                home=_value(row,"home_team_name","home_team")
                start=_datetime(row)
                if away and home and start and start+timedelta(hours=4)>now:
                    games[(away,home,start)]=(away,home,start)
        except Exception as exc:
            print("AHL schedule season",season,"unavailable:",type(exc).__name__)
    future=sorted(games.values(),key=lambda g:g[2])
    replacements={}
    for pid,team in targets.items():
        matches=[g for g in future if _norm(team) in (_norm(g[0]),_norm(g[1])) or
                 (_norm(team) and (_norm(team) in _norm(g[0]) or _norm(team) in _norm(g[1])))]
        result=[]
        # Only the next verified game is assigned to this team channel.
        if matches:
            away,home,start=matches[0]
            end=start+timedelta(hours=4)
            label=f"{away} @ {home}"
            local=start.astimezone(EASTERN)
            date=f"{local.strftime('%B')} {local.day}, {local.strftime('%I:%M %p').lstrip('0')} {local.tzname()}"
            if start>now:
                result.append(_programme(pid,f"Next Game: {label} ({local.strftime('%A')}, {date})",now,start))
            if end>now:
                result.append(_programme(pid,f"{label} ({date})",max(now,start),end))
            result.append(_programme(pid,"Event has Concluded",max(now,end),max(now,end)+timedelta(days=2)))
        else:
            result.append(_programme(pid,"No Game Scheduled",now,now+timedelta(days=2)))
        replacements[pid]=result
    programmes=[p for p in programmes if p.get("channel") not in replacements]
    for entries in replacements.values():programmes.extend(entries)
    print("AHL generated:",len(replacements),"team channels;",len(future),"verified future games")
    return programmes
