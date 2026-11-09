#!/usr/bin/env python3
"""Presentation-only sports XMLTV cleanup; preserves IDs, programme times and sources."""
import csv
import gzip
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
LEAGUES = ("NBA", "MLB", "NFL", "NHL", "MLS", "WNBA", "MILB", "AHL")
ET_ZONE = ZoneInfo("America/New_York")
QUALITY = re.compile(r"\s+(?:UHD|FHD|HD|SD|4K|1080P|720P)\s*$", re.I)
TEAM_ROW = re.compile(r"\b(?:NBA|MLB|NFL|NHL|MLS|WNBA|MILB|AHL)\s+TEAMS?\s*[-:|]\s*(.+)", re.I)
GAME_ROW = re.compile(r"\b(NBA|MLB|NFL|NHL|MLS|WNBA|MILB|AHL)\s+(?:GAME|GAMES)\s*0*(\d{1,3})\b", re.I)
REPLAY_ROW = re.compile(r"\bNFL\s+REPLAY\s+0*(\d{1,2})\b", re.I)
ARENA_ROW = re.compile(r"\bNBA\s+IN\s+(?:THE\s+)?ARENA\s*(?:GAME\s*)?0*(\d{1,2})\b", re.I)
DATE_TEXT = re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}\b", re.I)
TIME_TEXT = re.compile(r"\b\d{1,2}:\d{2}\s*(?:AM|PM)?\s*(?:EST|EDT|ET)\b", re.I)
MATCHUP = re.compile(r"\b[A-Za-z][A-Za-z .'-]{2,50}\s+(?:@|vs\.?|versus)\s+[A-Za-z][A-Za-z .'-]{2,50}", re.I)


def clean(name, group):
    name = re.sub(r"^\s*(?:US|USA|UK|CA|VIP)\s*[-|:]\s*", "", name, flags=re.I).strip()
    team = TEAM_ROW.search(name)
    if team:
        value = QUALITY.sub("", team.group(1).split(" : ")[0].strip())
        value = re.split(r"\s+(?:NOV|DEC|JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT)\s+\d", value, flags=re.I)[0]
        return value.strip(" -:|") .title() if value.strip(" -:|") else None
    replay = REPLAY_ROW.search(name)
    if replay and "INFO" not in name.upper() and "HIGHLIGHTS" not in name.upper():
        return f"NFL Replay {int(replay.group(1)):02d}"
    arena = ARENA_ROW.search(name)
    if arena:
        return f"NBA In Arena {int(arena.group(1)):02d}"
    game = GAME_ROW.search(name)
    if game:
        return f"{game.group(1).upper()} Game {int(game.group(2)):02d}"
    # Other sports team feeds sometimes omit "TEAMS" in their labels.
    for league in LEAGUES:
        m = re.search(r"\b" + league + r"\s+(?:TEAM|TEAMS)\s*[:|-]\s*(.+)", name, re.I)
        if m:
            return QUALITY.sub("", m.group(1)).strip().title()
    return None


def inventory():
    names = {}
    with (ROOT / "channels.csv").open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            sid = (row.get("StreamID") or "").strip()
            name = row.get("ChannelName") or ""
            group = row.get("Group") or ""
            if sid.isdigit() and any(x in (group + " " + name).upper() for x in LEAGUES):
                result = clean(name, group)
                if result:
                    names["xtream." + sid] = result
    return names


def date_time_from_programme(p):
    raw = p.get("start", "")
    try:
        dt = datetime.strptime(raw[:14], "%Y%m%d%H%M%S")
        # XMLTV offset in start is the real schedule timestamp, not replay date.
        offset = raw[15:].strip()
        if re.fullmatch(r"[+-]\d{4}", offset):
            from datetime import timezone, timedelta
            sign = 1 if offset[0] == "+" else -1
            minutes = sign * (int(offset[1:3]) * 60 + int(offset[3:5]))
            dt = dt.replace(tzinfo=timezone(timedelta(minutes=minutes))).astimezone(ET_ZONE)
            return dt.strftime("%b %-d, %Y at %-I:%M %p %Z")
    except ValueError:
        pass
    return None


def describe(p):
    title = (p.findtext("title") or "").strip()
    if not title:
        return None
    existing = (p.findtext("desc") or "").strip()
    if existing:
        return None  # Preserve meaningful upstream descriptions and Replay board dates.
    if not MATCHUP.search(title):
        return None
    # Titles containing their own event date/time take priority over XMLTV block start.
    date = DATE_TEXT.search(title)
    time = TIME_TEXT.search(title)
    if date or time:
        detail = " | ".join(x.group(0) for x in (date, time) if x)
        return f"{title} | {detail}" if detail else title
    when = date_time_from_programme(p)
    if when:
        return f"{title} | {when}"
    return title


def process(path, names):
    path = Path(path)
    with gzip.open(path, "rb") as f:
        root = ET.parse(f).getroot()
    renamed = described = 0
    for ch in root.findall("channel"):
        new = names.get(ch.get("id", ""))
        if new:
            display = ch.find("display-name")
            if display is None:
                display = ET.SubElement(ch, "display-name")
            if display.text != new:
                display.text = new
                renamed += 1
    for p in root.findall("programme"):
        cid = p.get("channel", "")
        if cid not in names:
            continue
        value = describe(p)
        if value:
            ET.SubElement(p, "desc", {"lang": "en"}).text = value
            described += 1
    tmp = path.with_name(path.name + ".tmp")
    with gzip.open(tmp, "wb") as f:
        ET.ElementTree(root).write(f, encoding="utf-8", xml_declaration=True)
    tmp.replace(path)
    print(f"{path}: {renamed} sports display names cleaned; {described} descriptions added")


if __name__ == "__main__":
    mapping = inventory()
    for item in sys.argv[1:]:
        process(item, mapping)
