# GitHub EPG generator — Provider-first sports channel naming

This is a replacement for the **existing** Python files in your EPG generator repo.

## Install
1. Replace `build_epg.py` with the supplied file in the repository root.
2. Add or replace `sports_channel_names.py` in the same directory.
3. Keep your existing GitHub Actions workflow, `channels.csv`, `matches.csv`, and repository secrets. Your existing workflow must call `python build_epg.py`.
4. Run your GitHub Actions EPG build. View downloadable channel reports under `reports/sports-renamed/` (or your existing reports artifact if the workflow publishes it).

## Rules applied to channel display names
- **FloSports:** parse the provider channel name (e.g. `FLO 002 : LIVE - ...`), NOT EPG2/EPG37.
- **ESPN Plus:** parse the provider channel name, NOT EPG2/EPG37.
- **NFL/NBA/NHL/AHL/MLS/MLB/MiLB numbered EVENT slots:** parse the provider channel name, NOT EPG2/EPG37. No league or sport prefix.
- **NCAAF 17+ and NCAAB event slots:** use EPG 2 numbered channel titles and game information, standardized as Football/Basketball. NCAAF 01–16 remain fixed network feeds.
- **Only dedicated NBA TEAMS, NFL TEAMS and NHL TEAMS channels** consult EPG37 for an exact team-feed-specific scheduled programme. If a unique matching EPG channel and programme is not available, display `No Game Scheduled`.
- No scheduled matchup in a numbered game slot: display EXACTLY `No Game Scheduled`, with no channel/league/slot prefix.
- FC for soccer; Basketball for hoops. Eastern time is formatted as `Nov 6 - 7:00 PM EST` (EST label by request).
- Other network channels and 24/7 feeds retain their original names.

**Important:** FloSports provider names may omit dates. Where a date is absent, the script uses the GitHub build's Eastern date and infers rollover from the ordered event feed times; such records are labeled `INFERRED_DATE_FROM_RUN_DAY` in the report. These are not officially verified dates. If the provider date is present, it is used instead. If no ET time can be parsed, the event slot is reported as `No Game Scheduled` rather than inventing a time.

The EPG generator may still use EPG2/EPG37 for its ordinary XMLTV programme listings; the restriction above applies to **channel title renaming**. IDs, stream URLs, login secrets, and existing programme data are not changed by this module.

## Exports
- `reports/sports-renamed/ALL_CHANNELS_Renamed.csv`
- `reports/sports-renamed/<CATEGORY>.csv`
- `reports/sports-renamed/channel-names.txt`
- `reports/sports-renamed/summary.csv`

The CSV keeps the original channel metadata and adds `OriginalChannelName`, `NewChannelName`, `MatchStatus`, `EPGSource`, `SourceChannelID`.


## NCAA exception (EPG 2)
- NCAAF 01–16 are **network feeds** and retain their original network display names.
- NCAAF 17–85 uses exact **NCAAF slot number** matches from EPG 2; game names and times come from EPG 2. A date missing from EPG 2's NCAAF labels is inferred as the next Saturday and clearly flagged in `MatchStatus`.
- NCAAB uses exact **NCAAB slot number** matches from EPG 2 (slot number wins over inconsistent provider EPG IDs), using titles, explicit dates and Eastern times in that source.
- Missing, ambiguous or undated games display exactly `No Game Scheduled`.
- FloSports, ESPN Plus and numbered professional-league event channels still use **provider names**, not EPG enrichment. NBA/NFL/NHL **team channels** still use EPG 37.
- Existing EPG IDs, XMLTV programme records and stream IDs are preserved.
