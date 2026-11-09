"""Capture Xtream NFL Replay information board and read it with OpenAI vision."""
import base64
import csv
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from nfl_replay_board import DATA, EAST, MATCH

ROOT = Path(__file__).resolve().parent


def request_json(url, payload=None, headers=None, timeout=90):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=body, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def locate_stream():
    base = os.environ["XTREAM_URL"].rstrip("/")
    user = os.environ["XTREAM_USERNAME"]
    password = os.environ["XTREAM_PASSWORD"]
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("XTREAM_URL must be a valid http(s) URL")
    root = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
    query = urllib.parse.urlencode({"username": user, "password": password, "action": "get_live_streams"})
    streams = request_json(root + "/player_api.php?" + query)
    if not isinstance(streams, list):
        raise RuntimeError("Xtream live stream inventory unavailable")
    matches = [s for s in streams if re.search(r"\\bNFL\\s*Replay\\s*Info\\s*HD\\b", str(s.get("name", "")), re.I)]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one NFL Replay Info HD feed; found {len(matches)}")
    stream_id = int(matches[0]["stream_id"])
    ext = str(matches[0].get("container_extension") or "ts").lower()
    if ext not in ("ts", "m3u8"):
        ext = "ts"
    return root + "/live/" + urllib.parse.quote(user, safe="") + "/" + urllib.parse.quote(password, safe="") + f"/{stream_id}.{ext}"


def capture(stream, directory):
    # Never print FFmpeg stderr: it can include the credential-bearing stream URL.
    for index, offset in enumerate((0, 8, 16, 24, 32, 40), 1):
        dest = directory / f"board-{index:02d}.jpg"
        command = ["ffmpeg", "-hide_banner", "-loglevel", "quiet", "-y",
                   "-ss", str(offset), "-i", stream, "-frames:v", "1",
                   "-q:v", "3", str(dest)]
        result = subprocess.run(command, capture_output=True, timeout=90)
        if result.returncode != 0 or not dest.exists() or dest.stat().st_size < 1000:
            raise RuntimeError(f"FFmpeg capture failed at frame {index}")
    return sorted(directory.glob("board-*.jpg"))


def read_board(images):
    content = [{"type": "text", "text": (
        "Read these screenshots of the NFL Replay Info HD board. "
        "Return JSON only: {\\\"start_date\\\":\\\"YYYY-MM-DD\\\","
        "\\\"end_date\\\":\\\"YYYY-MM-DD\\\","
        "\\\"replays\\\":[{\\\"number\\\":1,\\\"matchup\\\":\\\"Away vs Home\\\"}]}. "
        "Use the printed date range at the bottom of the board, not today's date. "
        "Read replay slot numbers and teams exactly as shown. Do not guess. "
        "If the date range cannot be read, return null dates. "
        "If a replay slot cannot be read confidently, omit it."
    )}]
    for image in images:
        data = base64.b64encode(image.read_bytes()).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + data, "detail": "high"}})
    response = request_json(
        "https://api.openai.com/v1/chat/completions",
        {"model": os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini"),
         "temperature": 0,
         "response_format": {"type": "json_object"},
         "messages": [{"role": "user", "content": content}]},
        {"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
         "Content-Type": "application/json"},
        timeout=180)
    return json.loads(response["choices"][0]["message"]["content"])


def validate_and_save(board):
    from datetime import date
    start = date.fromisoformat(board["start_date"])
    end = date.fromisoformat(board["end_date"])
    today = datetime.now(EAST).date()
    if (end - start).days != 6 or not start <= today <= end:
        raise ValueError("Board must contain a current, exact seven-day date range")
    replays = board.get("replays")
    if not isinstance(replays, list) or len(replays) != 14:
        raise ValueError("All 14 replay assignments must be confidently identified")
    found = {}
    for item in replays:
        n = int(item["number"])
        matchup = str(item["matchup"]).strip()
        if not 1 <= n <= 14 or n in found or not MATCH.fullmatch(matchup):
            raise ValueError(f"Invalid or duplicate NFL Replay slot: {n}")
        found[n] = matchup
    if set(found) != set(range(1, 15)):
        raise ValueError("NFL Replay slot numbers 1-14 are incomplete")
    DATA.parent.mkdir(parents=True, exist_ok=True)
    temp = DATA.with_suffix(".tmp")
    try:
        with temp.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["Replay", "StreamID", "StartDate", "EndDate", "Matchup"])
            for n in sorted(found):
                writer.writerow([n, 1329644 + n, start.isoformat(), end.isoformat(), found[n]])
        temp.replace(DATA)
    finally:
        temp.unlink(missing_ok=True)
    print(f"Validated and saved {len(found)} replay slots for {start} through {end}")


def main():
    # Temporary images never enter the repository or artifact uploads.
    with tempfile.TemporaryDirectory(prefix="nfl-replay-") as temp:
        folder = Path(temp)
        frames = capture(locate_stream(), folder)
        board = read_board(frames)
        validate_and_save(board)
        # Delete immediately after validated extraction and durable CSV write.
        for frame in frames:
            frame.unlink()
        print("Validated screenshots deleted")


if __name__ == "__main__":
    main()
