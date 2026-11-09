"""Refresh the committed AHL season CSV using verified schedule events and Xtream IDs."""
import csv
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from ahl_schedule import _season_events, _norm

ROOT = Path(__file__).resolve().parent
INVENTORY = ROOT / "channels.csv"
OUTPUT = ROOT / "reports" / "ahl-season-2026-27.csv"
EASTERN = ZoneInfo("America/New_York")

def team_name(name):
    import re
    name = re.sub(r"^.*?AHL\s+TEAMS\s*[-:|]\s*", "", name, flags=re.I)
    name = re.sub(r"\b(?:FHD|UHD|HD|SD|4K)\b", "", name, flags=re.I)
    return name.replace("LE HIGH VALLEY", "LEHIGH VALLEY").replace(
        "W-B/SCRANTON", "WILKES-BARRE/SCRANTON").strip()

def same(a,b):
    a,b=_norm(a),_norm(b)
    return a==b or (len(a)>10 and len(b)>10 and (a in b or b in a))

def main():
    with INVENTORY.open(newline="", encoding="utf-8-sig") as f:
        catalog = list(csv.DictReader(f))
    teams = {}
    for row in catalog:
        group=(row.get("Group") or "").upper()
        name=(row.get("ChannelName") or "").strip()
        sid=(row.get("StreamID") or "").strip()
        if "AHL" not in group or "AHL TEAMS" not in name.upper() or not sid or "####" in name:
            continue
        teams[sid]=(team_name(name),(row.get("EPGID") or "").strip())
    games=_season_events()
    if len(games)<1000:
        raise RuntimeError(f"Only {len(games)} season events; refusing incomplete CSV")
    fields=["Season","StreamID","XMLTV_ID","Team","Away","Home",
            "StartUTC","StartEastern","EndUTC","Event","Title"]
    rows=[]
    matched=set()
    for sid,(team,pid) in teams.items():
        for away,home,start in games:
            if not (same(team,away) or same(team,home)):
                continue
            matched.add((away,home,start))
            local=start.astimezone(EASTERN)
            date=f"{local.strftime('%B')} {local.day}, {local.strftime('%I:%M %p').lstrip('0')} EST"
            for xmlid in ["xtream."+sid]+([pid] if pid and pid!="xtream."+sid else []):
                rows.append(dict(zip(fields,["2026-27",sid,xmlid,team,away,home,
                    start.isoformat(),local.strftime("%Y-%m-%d %I:%M %p")+" EST",
                    (start+timedelta(hours=4)).isoformat(),f"{away} @ {home}",
                    f"{away} @ {home} ({date})"])))
    if len(matched)<900:
        raise RuntimeError(f"Only {len(matched)} games matched Xtream teams; verify renamed teams before publishing")
    OUTPUT.parent.mkdir(exist_ok=True)
    with OUTPUT.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader()
        w.writerows(sorted(rows,key=lambda r:(r["StartUTC"],r["StreamID"])))
    print(f"Published {len(rows)} StreamID schedule rows from {len(matched)} verified AHL games")

if __name__=="__main__":
    main()
