"""Generate FloSports 001-800 XMLTV programmes from a fresh Xtream inventory."""
import csv
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "v4" / "flosports-live.csv"
ET_ZONE = ZoneInfo("America/New_York")
MONTHS = {m: i for i, m in enumerate(("JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"), 1)}
DATE_TIME = re.compile(
    r"\b(?P<month>JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|MAY|JUN(?:E)?|JUL(?:Y)?|AUG(?:UST)?|SEP(?:T(?:EMBER)?)?|OCT(?:OBER)?|NOV(?:EMBER)?|DEC(?:EMBER)?)"
    r"\s+(?P<day>\d{1,2})(?:,?\s+(?P<year>20\d{2}))?"
    r"\s*[-–—,:]*\s*(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<ampm>AM|PM)\s*(?P<zone>ET|EST|EDT)\b", re.I)
ACRONYMS = {"NFL","NBA","NHL","MLB","MLS","NCAA","NCAAF","NCAAB","UFC","PFL","ACC","SEC","SIU","SMU","UNC","UCLA","USC","UAB","UTSA","FCS","FBS","A&M","TV","FC","USA","D1","D2","D3"}

def title_case(value):
    def word(m):
        w=m.group()
        if w.upper() in ACRONYMS:return w.upper()
        if w.lower() in ("vs","vs."):return "vs."
        return w[:1].upper()+w[1:].lower()
    return re.sub(r"[A-Za-zÀ-ÿ0-9&.']+",word,value)


# Source names can have a clock time without a date; do not invent dates.
TIME_ONLY = re.compile(r"\s*[-–—]\s*\d{1,2}:\d{2}\s*(?:AM|PM)\s*(?:ET|EST|EDT)(?:\s*/\s*\d{1,2}:\d{2}\s*(?:AM|PM)\s*UK)?\s*$", re.I)
INTERNAL_ID = re.compile(r"\s*\[\d{3,}\]\s*")
LEADING_STATUS = re.compile(r"^(?:LIVE|REPLAY|UPCOMING)\s*[-–—:]\s*",re.I)

def clean_event(label):
    label = INTERNAL_ID.sub(" ",label)
    label = TIME_ONLY.sub("",label)
    label = LEADING_STATUS.sub("",label.strip())
    label = re.sub(r"\s+", " ", label).strip(" -–—:/")
    return title_case(label)

def add_flosports_programmes(merged, channels, signatures):
    if not LIVE.exists():
        print("FloSports: awaiting first Xtream snapshot; no invented listings",flush=True)
        return 0
    with LIVE.open(newline="",encoding="utf-8-sig") as f:
        rows={int(row["FloSports"]):row for row in csv.DictReader(f)
              if row.get("FloSports","").isdigit() and 1<=int(row["FloSports"])<=800}
    if len(rows)!=800:
        print(f"FloSports: snapshot contains {len(rows)}/800 channels; missing numbers receive No Scheduled Event",flush=True)
    now=datetime.now(timezone.utc)
    horizon=now+timedelta(days=2)
    def stamp(t):return t.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S +0000")
    added=0
    def emit(cid,start,stop,title):
        nonlocal added
        if stop<=start:return
        p=ET.SubElement(merged,"programme",channel=cid,start=stamp(start),stop=stamp(stop))
        ET.SubElement(p,"title",lang="en").text=title
        signatures.add((cid,p.get("start"),p.get("stop"),title))
        added+=1
    for n in range(1,801):
        cid=f"FloSports.{n:03d}"
        if cid not in channels:
            ch=ET.SubElement(merged,"channel",id=cid)
            ET.SubElement(ch,"display-name").text=f"FloSports {n:03d}"
            channels[cid]=ch
        raw=(rows.get(n) or {}).get("OriginalName","")
        label=raw.split(":",1)[1].strip() if ":" in raw else ""
        match=DATE_TIME.search(label)
        if not match:
            event=clean_event(label)
            title=f"{n:03d} - Upcoming Event: {event}" if event else f"{n:03d} - No Scheduled Event"
            # Undated events use a rolling 24-hour programme block.
            emit(cid,now,now+timedelta(hours=24),title)
            continue
        event=clean_event(label[:match.start()])
        try:
            month=next(v for k,v in MONTHS.items() if match["month"].upper().startswith(k))
            hour=int(match["hour"])%12+(12 if match["ampm"].upper()=="PM" else 0)
            year=int(match["year"]) if match["year"] else now.astimezone(ET_ZONE).year
            local=datetime(year,month,int(match["day"]),hour,int(match["minute"]),tzinfo=ET_ZONE)
            if not match["year"]:
                if local.astimezone(timezone.utc)<now-timedelta(days=180):local=local.replace(year=year+1)
                elif local.astimezone(timezone.utc)>now+timedelta(days=180):local=local.replace(year=year-1)
            if match["zone"].upper() in ("EST","EDT"):
                expected=-5 if match["zone"].upper()=="EST" else -4
                if local.utcoffset().total_seconds()!=expected*3600:raise ValueError("Invalid zone")
            start=local.astimezone(timezone.utc)
            end=start+timedelta(hours=4)
        except (ValueError,StopIteration):
            emit(cid,now,horizon,f"{n:03d} - No Scheduled Event")
            continue
        if start>now:emit(cid,now,min(start,horizon),f"{n:03d} - Upcoming Event: {event}")
        if end>now and start<horizon:emit(cid,max(start,now),min(end,horizon),f"{n:03d} - {event}")
        if end<horizon:emit(cid,max(end,now),horizon,f"{n:03d} - Event Concluded")
    print(f"FloSports: {len(rows)} live names, 800 channel IDs, {added} programmes",flush=True)
    return added
