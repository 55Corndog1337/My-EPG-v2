DUAL FULL EPG + SPORTS MAPPING FOR TIVIMATE

Upload these three files to your repository (preserve paths):
  dual_sports_epg.py
  sports_overlay.py
  .github/workflows/build-epg-xtream.yml

Keep your existing build_epg.py, matches.csv and all other working files unchanged.
Required GitHub Actions secrets: PLAYLIST_URL, XTREAM_URL, XTREAM_USERNAME, XTREAM_PASSWORD.

The existing build_epg.py still generates site/epg.xml.gz unchanged.
The overlay creates two FULL XMLTV guides:
  site/epg-xtream.xml.gz = existing full guide + Xtream sports
  site/epg-m3u.xml.gz = existing full guide + mapped edited M3U sports

The M3U guide is designed for the private M3U produced in the workflow artifact:
  private/playlist-sports-mapped.m3u
The private M3U is NEVER committed/published. Download it from the GitHub Actions run.
If using the ORIGINAL M3U URL directly in TiviMate, sports channels with different
original tvg-id values will NOT auto-map. Use the private mapped M3U for those channels.

Exact M3U categories supported:
AM|USA|MLB, AM|USA|MiLB, AM|USA|NBA, AM|USA|MLS,
AM|USA|NHL, AM|USA|NFL, AM|USA|NCAA, AM|USA|FLO SPORTS TV.
Match only when sport + channel number identifies a unique channel on both sides.
Missing and ambiguous channels are not mapped; see reports/sports-m3u-mapping.csv.

Runs at midnight, 6 AM, noon and 6 PM Eastern (EST/EDT) using UTC candidates
and an Eastern-time guard. GitHub Actions scheduled runs can be delayed.

IMPORTANT: If your repo's build_epg.py writes site/epg.xml.gz, this workflow
preserves that output. The two derived guides do not replace the original guide.

LIMITATIONS: Dates missing from channel names are assigned to the next applicable
Eastern daily time slot; that date is an estimate, not a confirmed event date.
NCAAF network mapping requires EPG37 and its available college-football entries.

NBA IN THE ARENA UPDATE:
- NBA IN THE ARENA channels retain their own separate XMLTV IDs.
- If an Arena channel has an explicit event listing, that listing takes priority.
- If the Arena channel has no event details, the generator copies the matching numbered NBA GAME event (only if exactly one counterpart exists).
- Arena channels are matched separately from regular NBA channels in the edited M3U; absent channels are never invented.
- No changes are required to your existing build_epg.py.
