#!/usr/bin/env python3
"""Merge EPG 2 and 37 in full, UK EPG 6, and AHL."""
# Manual refresh requested; this commit triggers the V4 push workflow.
import gzip
import csv
from datetime import datetime, timedelta, timezone
import io
import os
import re
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "v4-output" / "epg.xml.gz"
SOURCES = {
    "epg2": "https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg2.xml.gz",
    "epg6": "https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg6.xml.gz",
    "epg37": "https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg37.xml.gz",
}
# EPG 2 is the full base; EPG 6 adds UK, EPG 37 adds sports teams.
UK = re.compile(r"^\s*(?:UK|UNITED KINGDOM|GB|GBR)\s*(?:[-|:–—]\s*|\b)", re.I)
SPORTS = re.compile(r"\b(?:NFL|NBA|NHL|MLB|MiLB|MLS|WNBA|AHL)\b", re.I)
# Recognize FloSports and alternate provider labels, including FloHoops and
# FLSPORTS spellings, across all three imported EPG sources.
FLOSPORTS = re.compile(
    r"(?<![A-Za-z0-9])(?:FLO[\\s._-]*SPORTS?|FL[\\s._-]*SPORTS?|"
    r"FLO(?:HOOPS|WRESTLING|RACING|FOOTBALL|VOLLEYBALL|HOCKEY|BASEBALL|"
    r"SOFTBALL|TRACK|GYMNASTICS|CHEER|MARCHING|BOWLING|BIKES|GRAPPLING|COMBAT|LIVE))"
    r"(?=$|[^A-Za-z])", re.I)

TEAM_HINT = re.compile(r"\b(?:team|feed|home|away)\b", re.I)
SPORTS_LEAGUES = ("NFL", "NBA", "NHL", "MLB", "MiLB", "MLS", "WNBA", "AHL")
# Exclude only the obsolete ESPN+ dummy IDs; retain genuine ESPN channel IDs.
def excluded_dummy_id(cid):
    match = re.fullmatch(r"dummy-(\d+)", cid or "", re.I)
    return bool(match and 3345444 <= int(match.group(1)) <= 3345943)

# ESPN+ 1-600 is generated exclusively from the live Xtream inventory.
# Exclude source copies from EPG 2, 6 and 37, including their programme rows.
ESPN_PLUS_NUMBER = re.compile(
    r"(?<![A-Za-z0-9])ESPN[\s._-]*(?:\+|PLUS)[\s._#-]*0*(\d{1,3})(?!\d)", re.I)

def source_espn_plus_number(channel):
    for label in [channel.get("id", ""), *display_names(channel)]:
        match = ESPN_PLUS_NUMBER.search(label)
        if match and 1 <= int(match.group(1)) <= 600:
            return int(match.group(1))
    return None

def select_channel(source, channel):
    # Preserve all EPG 2 and EPG 37 channels, including regular television.
    # EPG 6 contributes UK channels only.
    if source in ("epg2", "epg37"):
        return True
    if source == "epg6":
        return any(UK.match(name) for name in display_names(channel))
    return False

def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "My-EPG-combined/1.0"})
    with urllib.request.urlopen(req, timeout=180) as response:
        data = response.read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data

def display_names(channel):
    return [(n.text or "").strip() for n in channel.findall("display-name")]

def add_ahl(merged, all_channels, signatures):
    """Append the existing 2026-27 AHL team schedule; no missing Hamilton channel."""
    path = ROOT / "v4-mappings" / "ahl-season-2026-27.csv"
    if not path.exists():
        raise RuntimeError("AHL schedule CSV missing")
    by_team = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            cid = row.get("XMLTV_ID", "").strip()
            team = row.get("Team", "").strip()
            if not cid or not team or team.casefold() == "hamilton":
                continue
            try:
                start = datetime.fromisoformat(row["StartUTC"]).astimezone(timezone.utc)
                end = datetime.fromisoformat(row["EndUTC"]).astimezone(timezone.utc)
            except (ValueError, KeyError):
                continue
            if end <= start:
                continue
            by_team.setdefault((cid, team), []).append((start, end, row))
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=7)
    fmt = lambda dt: dt.strftime("%Y%m%d%H%M%S +0000")
    added = 0
    for (cid, team), events in by_team.items():
        events.sort(key=lambda e: e[0])
        if cid not in all_channels:
            channel = ET.SubElement(merged, "channel", id=cid)
            ET.SubElement(channel, "display-name").text = team
            all_channels[cid] = channel
        current = now
        for start, end, row in events:
            if end <= now or start >= horizon:
                continue
            if start > current:
                pre_end = min(start, horizon)
                upcoming = row.get("Event") or f'{row.get("Away")} @ {row.get("Home")}'
                title = "Next Game: " + upcoming + " " + start.strftime("%B %d %I:%M %p UTC")
                p = ET.SubElement(merged, "programme", channel=cid, start=fmt(current), stop=fmt(pre_end))
                ET.SubElement(p, "title").text = title
                added += 1
            game_start = max(start, now)
            game_end = min(end, horizon)
            if game_end > game_start:
                p = ET.SubElement(merged, "programme", channel=cid, start=fmt(game_start), stop=fmt(game_end))
                ET.SubElement(p, "title").text = row.get("Event") or f'{row.get("Away")} @ {row.get("Home")}'
                added += 1
                current = game_end
        if current < horizon:
            p = ET.SubElement(merged, "programme", channel=cid, start=fmt(current), stop=fmt(horizon))
            ET.SubElement(p, "title").text = "Event concluded"
            added += 1
    print(f"AHL: {len(by_team)} team channels, {added} programmes", flush=True)
    return added

def add_inventory_channels(merged, all_channels, excluded_epg2_ids):
    """Preserve every scoped Xtream channel even without a source listing."""
    path = ROOT / "v4" / "inventory.csv"
    if not path.exists():
        raise RuntimeError("Xtream inventory missing: refusing incomplete guide")
    added = 0
    rows = 0
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            group = (row.get("Group") or "").strip()
            if not (group.startswith("AM | USA |") or group.startswith("AM | CA |")
                    or group.startswith("EU | UK |") or group.startswith("VIP |")):
                continue
            name = (row.get("ChannelName") or "").strip()
            if not name or name.startswith("#####"):
                continue
            rows += 1
            epgid = (row.get("EPGID") or "").strip()
            streamid = (row.get("StreamID") or "").strip()
            cid = epgid or ("xtream-stream-" + streamid if streamid else "")
            if not cid or cid in all_channels or cid in excluded_epg2_ids or excluded_dummy_id(cid):
                continue
            channel = ET.SubElement(merged, "channel", id=cid)
            ET.SubElement(channel, "display-name").text = name
            all_channels[cid] = channel
            added += 1
    print(f"Xtream inventory: {rows} scoped rows, {added} additional channel IDs", flush=True)
    return added


def add_espn_programmes(merged, channels, signatures, guides):
    """Build ESPN+ 1-600 from the latest Xtream snapshot, not EPG6 programme data."""
    from zoneinfo import ZoneInfo
    path = ROOT / "v4" / "espn-plus-live.csv"
    if not path.exists():
        raise RuntimeError("Live ESPN+ snapshot missing; refusing stale ESPN+ listings")
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = {int(row["ESPNPlus"]): row for row in csv.DictReader(f)
                if row.get("ESPNPlus", "").isdigit() and 1 <= int(row["ESPNPlus"]) <= 600}
    if len(rows) != 600:
        raise RuntimeError(f"Expected 600 live ESPN+ channels, found {len(rows)}")
    eastern = ZoneInfo("America/New_York")
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=2)
    stamp = lambda dt: dt.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S +0000")
    event_re = re.compile(
        r"\b(?P<month>JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|MAY|JUN(?:E)?|JUL(?:Y)?|AUG(?:UST)?|SEP(?:T(?:EMBER)?)?|OCT(?:OBER)?|NOV(?:EMBER)?|DEC(?:EMBER)?)"
        r"\s+(?P<day>\d{1,2})(?:,?\s+(?P<year>20\d{2}))?"
        r"\s*[-–—]\s*(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<ampm>AM|PM)\s*(?P<zone>ET|EST|EDT)\b", re.I)
    months = {m: i for i, m in enumerate(("JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"),1)}
    def programme(cid, start, stop, title):
        if stop <= start:
            return 0
        p = ET.SubElement(merged, "programme", channel=cid, start=stamp(start), stop=stamp(stop))
        ET.SubElement(p, "title", lang="en").text = title
        signatures.add((cid, p.get("start"), p.get("stop"), title))
        return 1
    # Canonical XMLTV IDs: ESPN+ 1 = 1706.ESPN, ESPN+ 600 = 2305.ESPN.
    # Remove any imported programmes using those IDs before writing our schedule.
    targets = {f"{1705+n}.ESPN" for n in range(1, 601)}
    for p in list(merged.findall("programme")):
        if p.get("channel") in targets:
            merged.remove(p)
    added = 0
    for n in range(1, 601):
        row = rows.get(n, {})
        cid = f"{1705+n}.ESPN"
        if cid not in channels:
            ch = ET.SubElement(merged, "channel", id=cid)
            ET.SubElement(ch, "display-name").text = f"ESPN+ {n}"
            channels[cid] = ch
        else:
            # Keep a single channel definition and show the correct numbered name.
            ch = channels[cid]
            for node in ch.findall("display-name"):
                ch.remove(node)
            ET.SubElement(ch, "display-name").text = f"ESPN+ {n}"
        name = (row.get("OriginalName") or "").strip()
        label = name.split(":",1)[1].strip() if ":" in name else ""
        match = event_re.search(label)
        if not match:
            added += programme(cid, now, horizon, f"{n} - No Scheduled Event")
            continue
        event = label[:match.start()].strip(" -–—")
        # Capitalize each word in Xtream event titles, retaining standard acronyms.
        acronyms = {"NFL", "NBA", "NHL", "MLB", "MLS", "NCAA", "NCAAF", "NCAAB",
                    "UFC", "PFL", "ESPN", "ACC", "SEC", "SIU", "SMU", "UNC",
                    "UCLA", "USC", "UAB", "UTSA", "FCS", "FBS", "A&M", "TV", "FC"}
        def capitalize_token(token):
            if not token or token.isspace():
                return token
            if token.upper() in acronyms:
                return token.upper()
            if token.lower() in ("vs", "vs."):
                return "vs."
            return token[:1].upper() + token[1:].lower()
        event = re.sub(r"[A-Za-zÀ-ÿ0-9&.']+", lambda m: capitalize_token(m.group(0)), event)
        # Preserve established league acronyms even when adjacent to punctuation.
        event = re.sub(r"\\b(?:NCAA|NFL|NBA|NHL|MLB|MLS|ACC|SEC|ESPN|UFC|PFL)\\b",
                       lambda m: m.group(0).upper(), event, flags=re.I)
        try:
            month = next(v for k,v in months.items() if match["month"].upper().startswith(k))
            hour = int(match["hour"]) % 12 + (12 if match["ampm"].upper()=="PM" else 0)
            year = int(match["year"]) if match["year"] else now.astimezone(eastern).year
            local = datetime(year,month,int(match["day"]),hour,int(match["minute"]),tzinfo=eastern)
            if not match["year"]:
                if local.astimezone(timezone.utc) < now-timedelta(days=180):
                    local=local.replace(year=year+1)
                elif local.astimezone(timezone.utc) > now+timedelta(days=180):
                    local=local.replace(year=year-1)
            start=local.astimezone(timezone.utc)
            end=start+timedelta(hours=4)
            # ET is interpreted in America/New_York; explicit EST/EDT must agree.
            if match["zone"].upper() in ("EST","EDT"):
                expected = -5 if match["zone"].upper()=="EST" else -4
                if local.utcoffset().total_seconds()!=expected*3600:
                    raise ValueError("Timezone label disagrees with event date")
        except (ValueError, StopIteration):
            added += programme(cid, now, horizon, f"{n} - No Scheduled Event")
            continue
        label_date=local.strftime("%b %d, %Y")
        label_time=local.strftime("%I:%M %p").lstrip("0")+" ET"
        if start > now:
            added += programme(cid, now, min(start,horizon), f"{n} - Upcoming Event: {event}")
        if end > now and start < horizon:
            added += programme(cid, max(start,now), min(end,horizon),
                               f"{n} - {event}")
        if end < horizon:
            added += programme(cid, max(now,end), horizon, f"{n} - Event Concluded")
    print(f"ESPN+ live snapshot: {len(rows)} numbered channels; {added} programmes",flush=True)
    return added

def add_college_programmes(merged, channels, signatures, guides):
    """Map NCAAB/NCAAF from approved sources and unambiguous numbered EPG6 channels."""
    import json
    total = 0
    for league, filename in (("NCAAB", "ncaa-basketball.json"),
                             ("NCAAF", "ncaa-football.json")):
        with (ROOT / "v4-mappings" / filename).open(encoding="utf-8") as f:
            mappings = json.load(f)["mappings"]
        # EPG6 is additional, not a substitute for the approved EPG2/37 mappings.
        # Only explicit numbered college-game labels qualify; never use a generic
        # matchup or ESPN/ESPN2 channel to guess which game number it belongs to.
        numbered = re.compile(
            r"\\b" + league + r"\\s*(?:GAME\\s*)?0*(\\d{1,3})\\b", re.I)
        epg6_by_number = defaultdict(set)
        for channel in guides["epg6"].findall("channel"):
            cid = channel.get("id")
            if not cid:
                continue
            for label in [cid, *display_names(channel)]:
                match = numbered.search(label)
                if match:
                    epg6_by_number[int(match.group(1))].add(cid)
        source_to_targets = defaultdict(lambda: defaultdict(set))
        targets_to_names = defaultdict(list)
        for item in mappings:
            match = numbered.search(item.get("channel", ""))
            if not match:
                continue
            number = int(match.group(1))
            original = (item.get("original_xtream_epgid") or "").strip()
            stream = (item.get("xtream_stream_id") or "").strip()
            target = original or ("xtream-stream-" + stream if stream else "")
            if not target:
                continue
            targets_to_names[target].append(item["channel"])
            if target not in channels:
                channel = ET.SubElement(merged, "channel", id=target)
                ET.SubElement(channel, "display-name").text = item["channel"]
                channels[target] = channel
            source = item.get("source")
            source_id = (item.get("source_channel_id") or "").strip()
            if source in ("epg2", "epg37") and source_id:
                source_to_targets[source][source_id].add(target)
            for epg6_id in epg6_by_number.get(number, ()):
                source_to_targets["epg6"][epg6_id].add(target)
        for target, names in targets_to_names.items():
            if len(names) > 1:
                print(f"{league}: shared original ID {target}: {', '.join(names)}", flush=True)
        by_source = {}
        for source, source_ids in source_to_targets.items():
            count = 0
            guide = guides.get(source)
            if guide is None:
                continue
            for programme in guide.findall("programme"):
                targets = source_ids.get(programme.get("channel"))
                if not targets:
                    continue
                for target in targets:
                    duplicate = ET.fromstring(ET.tostring(programme, encoding="utf-8"))
                    duplicate.set("channel", target)
                    sig = (target, duplicate.get("start"), duplicate.get("stop"),
                           duplicate.findtext("title", default=""))
                    if sig in signatures:
                        continue
                    signatures.add(sig)
                    merged.append(duplicate)
                    count += 1
            by_source[source] = count
            total += count
        print(f"{league}: {len(mappings)} approved mappings, "
              f"{len(targets_to_names)} output IDs, EPG6 numbered channels "
              f"{sum(len(v) for v in epg6_by_number.values())}, "
              f"new programmes by source {by_source}", flush=True)
    return total


# Adjust only written sports times, never XMLTV scheduling attributes.
WRITTEN_TIME = re.compile(r"(?<!\\d)(?P<hour>1[0-2]|0?[1-9]):(?P<minute>[0-5]\\d)\\s*(?P<period>AM|PM)\\b(?:\\s*(?P<zone>EST|EDT|ET|UTC|GMT|PST|PDT|CST|CDT))?", re.I)
TARGET_SPORT = re.compile(r"\\b(?:NBA|NHL|NFL|NCAAF|NCAAB|NCAA|ESPN\\s*\\+|ESPN\\s*PLUS|ESPNPLUS)\\b", re.I)

def shift_written_sports_times(merged, channels):
    eligible = {cid for cid, channel in channels.items()
                if TARGET_SPORT.search(" ".join([cid, *display_names(channel)]))}
    updated = 0
    # Xtream can embed the event time in the channel display-name itself.
    # Shift that written label too, while preserving the XMLTV channel ID.
    def shift_text(value):
        def replace(match):
            if (match.group("zone") or "").upper() == "EST":
                return match.group(0)
            hour = int(match.group("hour")) % 12
            if match.group("period").upper() == "PM":
                hour += 12
            hour = (hour + 3) % 24
            period = "AM" if hour < 12 else "PM"
            return f"{hour % 12 or 12}:{match.group('minute')} {period} EST"
        return WRITTEN_TIME.sub(replace, value)

    for cid in eligible:
        if re.fullmatch(r"(?:ESPN(?:\.PLUS|Plus)\.\d+|(?:1[7-9]\d\d|2[0-2]\d\d|230[0-5])\.ESPN)", cid, re.I):
            continue
        for node in channels[cid].findall("display-name"):
            if node.text:
                new_text = shift_text(node.text)
                if new_text != node.text:
                    node.text = new_text
                    updated += 1
    for programme in merged.findall("programme"):
        if programme.get("channel") not in eligible or re.fullmatch(r"ESPN\.PLUS\.\d+", programme.get("channel", ""), re.I):
            continue
        for tag in ("title", "desc", "sub-title"):
            for node in programme.findall(tag):
                if not node.text:
                    continue
                def replace(match):
                    if (match.group("zone") or "").upper() == "EST":
                        return match.group(0)
                    hour = int(match.group("hour")) % 12
                    if match.group("period").upper() == "PM":
                        hour += 12
                    hour = (hour + 3) % 24
                    period = "AM" if hour < 12 else "PM"
                    return f"{hour % 12 or 12}:{match.group('minute')} {period} EST"
                new_text = shift_text(node.text)
                if new_text != node.text:
                    node.text = new_text
                    updated += 1
    print(f"Sports written-time fields adjusted (channel names and programme text): {updated}; XMLTV start/stop unchanged", flush=True)

def main():
    merged = ET.Element("tv", {"generator-info-name": "Combined EPG 2+6+37"})
    all_channels = {}
    signatures = set()
    total = 0
    guides = {}
    excluded_epg2_ids = set()
    for source, url in SOURCES.items():
        data = download(url)
        tv = ET.fromstring(data)
        if source in ('epg2', 'epg6', 'epg37'):
            guides[source] = tv
        selected = {}
        for channel in tv.findall("channel"):
            cid = channel.get("id")
            if not cid or excluded_dummy_id(cid) or source_espn_plus_number(channel) is not None or not select_channel(source, channel):
                continue
            if any(FLOSPORTS.search(label) for label in [cid, *display_names(channel)]):
                excluded_epg2_ids.add(cid)
                continue
            # Identical IDs are shared; keep one channel entry, combine listings.
            selected[cid] = cid
            if cid not in all_channels:
                all_channels[cid] = channel
                merged.append(channel)
        count = 0
        for programme in tv.findall("programme"):
            cid = programme.get("channel")
            if cid not in selected:
                continue
            sig = (cid, programme.get("start"), programme.get("stop"),
                   programme.findtext("title", default=""))
            if sig in signatures:
                continue
            signatures.add(sig)
            merged.append(programme)
            count += 1
        print(f"{source}: {len(selected)} channels, {count} programmes", flush=True)
        total += count
    print(f"Excluded {len(excluded_epg2_ids)} FloSports channel IDs from EPG 2, 6 and 37", flush=True)
    total += add_espn_programmes(merged, all_channels, signatures, guides)
    total += add_college_programmes(merged, all_channels, signatures, guides)
    add_inventory_channels(merged, all_channels, excluded_epg2_ids)
    total += add_ahl(merged, all_channels, signatures)
    shift_written_sports_times(merged, all_channels)
    if not all_channels or not total:
        raise RuntimeError("No matching channels/programmes; existing guide preserved")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=OUT.parent, suffix=".tmp", delete=False) as f:
        tmp = Path(f.name)
    try:
        with gzip.open(tmp, "wb", compresslevel=6) as f:
            f.write(ET.tostring(merged, encoding="utf-8", xml_declaration=True))
        tmp.replace(OUT)
    finally:
        tmp.unlink(missing_ok=True)
    print(f"Published {len(all_channels)} unique channels and {total} programmes: {OUT}")

if __name__ == "__main__":
    main()
