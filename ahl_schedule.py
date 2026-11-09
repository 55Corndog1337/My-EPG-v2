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

def _legacy_run(catalog,channels,programmes,reports):
    now=datetime.now(timezone.utc)
    targets={}
    for row in catalog:
        name=(row.get("ChannelName") or "").strip()
        group=(row.get("Group") or "").upper()
        if "AHL" not in name.upper() and "AHL" not in group:
            continue
        if re.search(r"\b(?:GAME|REPLAY)\s*\d+\b",name,re.I) or not (row.get("StreamID") or "").strip() or "####" in name:
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
            team=re.sub(r"^(?:(?:US|USA|CA|VIP|AHL|TEAMS?)\s*[-:|]\s*)+","",name,flags=re.I)
            team=re.sub(r"\b(?:AHL|TEAMS?|HD|FHD|UHD|4K)\b"," ",team,flags=re.I).strip(" -:|")
            team=re.sub(r"\s+"," ",team).strip()
            team=team.replace("LE HIGH VALLEY","LEHIGH VALLEY").replace("W-B/SCRANTON","WILKES-BARRE/SCRANTON")
            if team:
                targets[pid]=team
                provider_id=(row.get("EPGID") or "").strip()
                if provider_id and provider_id != pid:
                    if provider_id not in channels:
                        alias=ET.Element("channel",{"id":provider_id})
                        ET.SubElement(alias,"display-name").text=name
                        channels[provider_id]=alias
                    targets[provider_id]=team
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
            date=f"{local.strftime('%B')} {local.day}, {local.strftime('%I:%M %p').lstrip('0')} {'EST'}"
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


# Full 2026-27 AHL season source, with a verified StreamID-to-team inventory.
# TheSportsDB league 4738; schedule is re-fetched at every build.
def _season_events():
    from urllib.parse import urlencode
    url = ("https://www.thesportsdb.com/api/v1/json/3/eventsseason.php?"
           + urlencode({"id": "4738", "s": "2026-2027"}))
    req = urllib.request.Request(url, headers={"User-Agent": "My-EPG-v2/2.0"})
    with urllib.request.urlopen(req, timeout=35) as response:
        payload = json.load(response)
    raw_events = payload.get("events") or []
    result = {}
    for e in raw_events:
        away = (e.get("strAwayTeam") or "").strip()
        home = (e.get("strHomeTeam") or "").strip()
        if not away or not home or _norm(away) == _norm(home):
            continue
        stamp = (e.get("strTimestamp") or "").strip()
        if not stamp:
            date = (e.get("dateEvent") or "").strip()
            clock = (e.get("strTime") or "").strip()
            if not date or not clock:
                continue
            stamp = date + "T" + clock
        try:
            start = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if start.tzinfo is None:
                # TheSportsDB dateEvent/strTime fields are UTC.
                start = start.replace(tzinfo=timezone.utc)
            start = start.astimezone(timezone.utc)
        except ValueError:
            continue
        if not (datetime(2026, 10, 2, tzinfo=timezone.utc) <= start <=
                datetime(2027, 4, 13, tzinfo=timezone.utc)):
            continue
        result[(away, home, start)] = (away, home, start)
    return sorted(result.values(), key=lambda x: x[2])


def run(catalog, channels, programmes, reports):
    """Rolling seven-day AHL guide, sourced from the committed full-season CSV.

    No live AHL fetch. The 4-hourly master build refreshes the 24-hour window.
    """
    import csv
    from pathlib import Path
    now = datetime.now(timezone.utc)
    day_end = now + timedelta(days=7)
    source = Path(__file__).resolve().parent / "reports" / "ahl-season-2026-27.csv"
    if not source.is_file():
        print("AHL static CSV missing:", source)
        return programmes

    by_team = {}
    with source.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            pid = (row.get("XMLTV_ID") or "").strip()
            if not pid.startswith("xtream."):
                continue
            try:
                start = datetime.fromisoformat(row["StartUTC"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(row["EndUTC"].replace("Z", "+00:00"))
                if start.tzinfo is None or end.tzinfo is None:
                    continue
                by_team.setdefault(pid, {})[(start, row["Event"])] = (
                    start, end, row["Event"])
            except (ValueError, KeyError):
                continue

    # Match the Xtream inventory, not schedule team names, to avoid reassigning
    # Bridgeport's existing ID to the new Hamilton franchise.
    mapped = {}
    for row in catalog:
        group = (row.get("Group") or "").upper()
        name = (row.get("ChannelName") or "").strip()
        sid = (row.get("StreamID") or "").strip()
        if "AHL" not in group or "AHL TEAMS" not in name.upper() or not sid:
            continue
        pid = "xtream." + sid
        mapped[pid] = name
        if pid not in channels:
            ch = ET.Element("channel", {"id": pid})
            ET.SubElement(ch, "display-name").text = name
            channels[pid] = ch

    programmes = [p for p in programmes if p.get("channel") not in mapped]
    def fmt(start):
        local = start.astimezone(EASTERN)
        return f"{local.strftime('%A, %B')} {local.day}, {local.strftime('%I:%M %p').lstrip('0')} {local.strftime('%Z')}"
    count = 0
    for pid in mapped:
        games = sorted(by_team.get(pid, {}).values())
        cursor = now
        while cursor < day_end:
            active = next((g for g in games if g[0] <= cursor < g[1]), None)
            if active:
                start, end, event = active
                until = min(end, day_end)
                title = f"{event} ({fmt(start)})"
            else:
                future = next((g for g in games if g[0] > cursor), None)
                previous = next((g for g in reversed(games) if g[1] <= cursor), None)
                if future:
                    start, end, event = future
                    until = min(start, day_end)
                    title = f"Next Game: {event} ({fmt(start)})"
                elif previous:
                    until = day_end
                    title = "Event has Concluded"
                else:
                    until = day_end
                    title = "No Game Scheduled"
            if until <= cursor:
                break
            programmes.append(_programme(pid, title, cursor, until))
            count += 1
            cursor = until
    print("AHL STATIC CSV ROLLING 7D:", len(mapped),
          "Xtream IDs;", count, "programmes; source", source)
    return programmes


def _unused_dynamic_run(catalog, channels, programmes, reports):
    import csv
    from pathlib import Path
    from collections import defaultdict
    now = datetime.now(timezone.utc)
    # CSV is the authoritative schedule. This build never replaces it with a
    # live network feed; the separate refresh job updates the CSV on GitHub.
    source_csv = Path(reports).parent / "reports" / "ahl-season-2026-27.csv"
    if not source_csv.is_file():
        print("AHL CSV absent: run the AHL schedule refresh workflow first")
        return _legacy_run(catalog, channels, programmes, reports)
    games_by_key = {}
    with source_csv.open(newline="", encoding="utf-8") as handle:
        for item in csv.DictReader(handle):
            try:
                away, home = item["Away"].strip(), item["Home"].strip()
                start = datetime.fromisoformat(item["StartUTC"].replace("Z", "+00:00"))
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                start = start.astimezone(timezone.utc)
                if away and home:
                    games_by_key[(away, home, start)] = (away, home, start)
            except (KeyError, ValueError):
                continue
    games = sorted(games_by_key.values(), key=lambda x: x[2])
    print("AHL loaded schedule FROM GITHUB CSV:", len(games), "games")
    # StreamID comes only from the Xtream inventory, never from the schedule feed.
    teams = {}
    for row in catalog:
        group = (row.get("Group") or "").upper()
        name = (row.get("ChannelName") or "").strip()
        sid = (row.get("StreamID") or "").strip()
        if "AHL" not in group or not sid or "####" in name or "AHL TEAMS" not in name.upper():
            continue
        team = re.sub(r"^.*?AHL\s+TEAMS\s*[-:|]\s*", "", name, flags=re.I)
        team = re.sub(r"\b(?:FHD|UHD|HD|SD|4K)\b", "", team, flags=re.I).strip()
        team = team.replace("LE HIGH VALLEY", "LEHIGH VALLEY").replace(
            "W-B/SCRANTON", "WILKES-BARRE/SCRANTON")
        if team:
            teams[sid] = (team, (row.get("EPGID") or "").strip(), name)
    if not teams:
        print("AHL season: no Xtream AHL team StreamIDs in inventory")
        return programmes
    aliases = {"WILKESBARRESCRANTONPENGUINS": "WILKESBARRESCRANTONPENGUINS",
               "LEHIGHVALLEYPHANTOMS": "LEHIGHVALLEYPHANTOMS"}
    def same_team(a, b):
        aa, bb = _norm(a), _norm(b)
        return aa == bb or (len(aa) > 10 and len(bb) > 10 and
                            (aa in bb or bb in aa))
    season_rows = []
    replacements = defaultdict(list)
    for sid, (team, provider_id, channel_name) in sorted(teams.items()):
        ids = ["xtream." + sid] + ([provider_id] if provider_id and provider_id != "xtream." + sid else [])
        matches = [(away, home, start) for away, home, start in games
                   if same_team(team, away) or same_team(team, home)]
        for pid in ids:
            if pid not in channels:
                ch = ET.Element("channel", {"id": pid})
                ET.SubElement(ch, "display-name").text = channel_name
                channels[pid] = ch
        for away, home, start in matches:
            local = start.astimezone(EASTERN)
            date = f"{local.strftime('%B')} {local.day}, {local.strftime('%I:%M %p').lstrip('0')} EST"
            matchup = f"{away} @ {home}"
            for pid in ids:
                season_rows.append({
                    "Season": "2026-27", "StreamID": sid, "XMLTV_ID": pid,
                    "Team": team, "Away": away, "Home": home,
                    "StartUTC": start.isoformat(),
                    "StartEastern": local.strftime("%Y-%m-%d %I:%M %p") + " EST",
                    "EndUTC": (start + timedelta(hours=4)).isoformat(),
                    "Event": matchup, "Title": f"{matchup} ({date})"})
        # Only one active/future game at a time, matching the existing state machine.
        future = [(a, h, t) for a, h, t in matches if t + timedelta(hours=4) > now]
        for pid in ids:
            if not future:
                replacements[pid].append(_programme(pid, "No Game Scheduled", now,
                                                    now + timedelta(days=2)))
                continue
            away, home, start = future[0]
            end = start + timedelta(hours=4)
            local = start.astimezone(EASTERN)
            date = f"{local.strftime('%B')} {local.day}, {local.strftime('%I:%M %p').lstrip('0')} EST"
            matchup = f"{away} @ {home}"
            if start > now:
                replacements[pid].append(_programme(
                    pid, f"Next Game: {matchup} ({local.strftime('%A')}, {date})", now, start))
            if end > now:
                replacements[pid].append(_programme(
                    pid, f"{matchup} ({date})", max(now, start), end))
            replacements[pid].append(_programme(
                pid, "Event has Concluded", max(now, end),
                max(now, end) + timedelta(days=2)))
    reports = Path(reports)
    reports.mkdir(parents=True, exist_ok=True)
    filename = reports / "ahl-season-2026-27.csv"
    fields = ["Season", "StreamID", "XMLTV_ID", "Team", "Away", "Home",
              "StartUTC", "StartEastern", "EndUTC", "Event", "Title"]
    with filename.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(season_rows)
    programmes = [p for p in programmes if p.get("channel") not in replacements]
    for entries in replacements.values():
        programmes.extend(entries)
    print("AHL FULL SEASON:", len(games), "verified games;",
          len(teams), "Xtream team StreamIDs;",
          len(season_rows), "CSV mappings;",
          len(replacements), "EPG channels")
    return programmes
