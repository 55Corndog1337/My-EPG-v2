"""Weekly NFL Replay Info HD board -> verified replay assignments and XMLTV."""
import csv
import re
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "reports" / "nfl-replay-board.csv"
EAST = ZoneInfo("America/New_York")
MONTH = {m.lower(): i for i, m in enumerate(
    ("", "January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December")) if m}
MONTH.update({k[:3]: v for k, v in list(MONTH.items())})
TEAM = re.compile(r"[A-Za-z][A-Za-z .'-]{2,55}")
MATCH = re.compile(r"(?P<away>[A-Za-z][A-Za-z .'-]{2,48}?)\s*(?:@|vs\.?|versus|at)\s*(?P<home>[A-Za-z][A-Za-z .'-]{2,48})", re.I)
SLOT = re.compile(r"(?:NFL\s*REPLAY\s*)?(?:#\s*)?(?P<n>1[0-4]|[1-9])\s*[\).:\-|]\s*(?P<game>.+)", re.I)
RANGE = re.compile(r"(?P<m1>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s*(?P<d1>\d{1,2})\s*(?:-|–|—|to|through)\s*(?:(?P<m2>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s*)?(?P<d2>\d{1,2})(?:\s*,?\s*(?P<year>20\d{2}))?", re.I)


def parse_range(text, today):
    candidates = []
    for m in RANGE.finditer(text):
        try:
            y = int(m.group("year") or today.year)
            a = date(y, MONTH[m.group("m1").lower()], int(m.group("d1")))
            b = date(y, MONTH[(m.group("m2") or m.group("m1")).lower()], int(m.group("d2")))
            if b < a:
                b = b.replace(year=y + 1)
            if 0 <= (b-a).days <= 13 and a <= today + timedelta(days=7) and b >= today - timedelta(days=7):
                candidates.append((a, b))
        except (ValueError, KeyError):
            pass
    return candidates


def capture_ocr(directory):
    frames = sorted(Path(directory).glob("*.png"))
    if not frames:
        raise RuntimeError("No FFmpeg frames available")
    return [subprocess.run(["tesseract", str(p), "stdout", "--psm", "11"],
            check=True, text=True, capture_output=True).stdout for p in frames]


def extract(texts, today):
    ranges = Counter(r for text in texts for r in set(parse_range(text, today)))
    if not ranges:
        raise ValueError("Date range at bottom of board was not recognized; refusing stale assignments")
    period, votes = ranges.most_common(1)[0]
    if votes < min(2, len(texts)):
        raise ValueError("Board date range not confirmed across screenshots")
    candidates = {}
    for text in texts:
        for line in text.splitlines():
            line = line.strip()
            m = SLOT.search(line)
            if not m:
                continue
            match = MATCH.search(m.group("game"))
            if not match:
                continue
            n = int(m.group("n"))
            away = re.sub(r"\s+", " ", match.group("away")).strip(" .-|")
            home = re.sub(r"\s+", " ", match.group("home")).strip(" .-|")
            if len(away) < 3 or len(home) < 3:
                continue
            candidates.setdefault(n, Counter())[(away, home)] += 1
    accepted = {}
    for n, votes_for in candidates.items():
        (away, home), count = votes_for.most_common(1)[0]
        if count >= min(2, len(texts)) and (len(votes_for) == 1 or count > votes_for.most_common(2)[1][1]):
            accepted[n] = f"{away} vs {home}"
    if len(accepted) < 8:
        raise ValueError(f"Only {len(accepted)} replay assignments confirmed; refusing incomplete OCR")
    return period, accepted


def update_board(directory):
    today = datetime.now(EAST).date()
    period, assignments = extract(capture_ocr(directory), today)
    DATA.parent.mkdir(parents=True, exist_ok=True)
    temp = DATA.with_suffix(".tmp")
    with temp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Replay", "StreamID", "StartDate", "EndDate", "Matchup"])
        for n, matchup in sorted(assignments.items()):
            writer.writerow([n, 1329644 + n, period[0].isoformat(), period[1].isoformat(), matchup])
    temp.replace(DATA)
    print(f"Confirmed NFL replay board: {period[0]} to {period[1]}, {len(assignments)} channels")


def apply(catalog, channels, programmes):
    """Always publish seven daily blocks for the 14 existing NFL Replay feeds.

    Verified board assignments are used only inside their valid date range.
    Missing, unreadable, or expired board data falls back to static labels.
    """
    today = datetime.now(EAST).date()
    verified = {}
    if DATA.exists():
        try:
            with DATA.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            for row in rows:
                n = int(row["Replay"])
                start = date.fromisoformat(row["StartDate"])
                end = date.fromisoformat(row["EndDate"])
                sid = str(1329644 + n)
                matchup = row["Matchup"].strip()
                if (1 <= n <= 14 and row["StreamID"] == sid
                        and MATCH.fullmatch(matchup)
                        and start <= end and (end - start).days <= 13):
                    verified[n] = (matchup, start, end)
        except (ValueError, KeyError, OSError, csv.Error) as exc:
            print("NFL Replay board unavailable; using static fallback:", type(exc).__name__)
            verified = {}

    live_ids = {str(r.get("StreamID", "")).strip() for r in catalog}
    replay_ids = {
        n: "xtream." + str(1329644 + n)
        for n in range(1, 15)
        if str(1329644 + n) in live_ids
    }
    if not replay_ids:
        print("NFL Replay: no matching Xtream streams; no synthetic channels added")
        return programmes

    # Replace old replay programme rows, including incorrect donor listings.
    programmes = [p for p in programmes if p.get("channel") not in set(replay_ids.values())]
    for n, pid in replay_ids.items():
        if pid not in channels:
            ch = ET.Element("channel", {"id": pid})
            ET.SubElement(ch, "display-name").text = f"NFL Replay {n}"
            channels[pid] = ch
        for offset in range(7):
            day = today + timedelta(days=offset)
            a = datetime(day.year, day.month, day.day, tzinfo=EAST)
            b = a + timedelta(days=1)
            p = ET.Element("programme", {
                "channel": pid,
                "start": a.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S +0000"),
                "stop": b.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S +0000")})
            assignment = verified.get(n)
            if assignment and assignment[1] <= day <= assignment[2]:
                matchup, start, end = assignment
                title = f"{matchup} ({start.strftime('%b')} {start.day}–{end.strftime('%b')} {end.day})"
                description = (
                    f"{matchup} | Board range: {start.isoformat()} to {end.isoformat()} | "
                    "24-hour replay listing; kickoff time not supplied by board")
            else:
                title = f"NFL Replay {n}"
                description = "NFL Replay channel; verified matchup information unavailable"
            ET.SubElement(p, "title", {"lang": "en"}).text = title
            ET.SubElement(p, "desc", {"lang": "en"}).text = description
            programmes.append(p)
    print(f"NFL Replay: {len(replay_ids)} Xtream channels; seven 24-hour blocks each; "
          f"{len(verified)} verified board assignments available")
    return programmes


if __name__ == "__main__":
    update_board(sys.argv[1] if len(sys.argv) > 1 else "snapshots")
