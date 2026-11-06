# My-EPG-v2 — NCAAF and event title rebuild

Copy `dual_sports_epg.py`, `sports_overlay.py`, `match_utils.py`, and `.github/workflows/build-epg-xtream.yml` into your repository at the same paths. **Keep your existing `build_epg.py` unchanged.**

Required GitHub Actions secrets: `PLAYLIST_URL`, `XTREAM_URL`, `XTREAM_USERNAME`, `XTREAM_PASSWORD`.

Run **Actions → Build full Xtream and M3U EPGs → Run workflow**. The workflow downloads EPG37, runs your existing full EPG builder, overlays sports schedules, and publishes `site/epg-xtream.xml.gz` and `site/epg-m3u.xml.gz`.

NCAAF 01–16: fixed EPG37 network mapping, qualifying college-football shows only. Before a scheduled game: title `Upcoming`, with matchup/date/time in description. During: clean title only. After: `Signing Off`. The same titles apply to dated Xtream events. Undated events do **not** acquire a guessed date; they show `Upcoming` with an undated description instead of a fictional event window. Paramount/MAX PPV without event details show their channel names.

The guide overlay retains ordinary programmes from `site/epg.xml.gz`. Channel IDs are unchanged. Playlist URLs and credentials are not included in the ZIP.

Run tests: `python -m unittest discover -p "test_*.py"`.
