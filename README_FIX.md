# GitHub EPG generator — HTTP 403 fix

## Replace these files

Replace the repository-root `build_epg.py` with this package's `build_epg.py`.
Keep `sports_channel_names.py` beside it. All existing naming rules are retained:

- FloSports, ESPN Plus, and numbered professional-league game slots: extract event names from provider channel names.
- NBA, NFL, and NHL **team** channels: use EPG 37 for date/opponent/time.
- NCAAF 01–16: preserve network feed names; NCAAF event slots beginning at 17 and NCAAB event slots use EPG 2.
- Empty slots: exactly `No Game Scheduled`.
- Dates and times in Eastern time, with standard channel display formatting; original IDs remain intact.

## Why the original build failed

The existing script retrieves EPG 2 and EPG 37 over HTTPS. When a source returns HTTP 403, `urllib.request.urlopen()` raises an exception and the build used to stop immediately. 403 means access is forbidden by that server; a code change cannot guarantee access to a restricted URL.

The updated download handler:
1. Reports `WARNING: epg2 source at raw.githubusercontent.com failed: HTTP 403` (or epg37, as appropriate), without printing secret query strings.
2. Retries transient HTTP 408, 429, 5xx errors but does not waste time retrying permanent 403s.
3. Falls back to a guide file from the repository if provided.
4. Continues if only one guide is accessible; if neither works, fails with a useful message and does not publish a misleading empty guide.
5. Reuses the guide data already downloaded and avoids a redundant EPG2 request during WATE fallback.

## Optional fallback guide files

If the remote source is denied, add one or both of these to your repository:

    sources/epg2.xml.gz
    sources/epg37.xml.gz

Or set GitHub Actions environment variables for verified sources:

    EPG2_URL: https://your-accessible-public-xmltv-source/epg2.xml.gz
    EPG37_URL: https://your-accessible-public-xmltv-source/epg37.xml.gz

Or set file paths:

    EPG2_FILE: sources/epg2.xml.gz
    EPG37_FILE: sources/epg37.xml.gz

Do not commit credentials or private stream URLs. Local fallback files must be current, valid XMLTV guides. A stale guide cannot supply fresh schedules. The original default URLs have NOT been replaced or proven accessible.

## GitHub Actions

Keep your existing workflow's `python build_epg.py` invocation; no Windows program is needed. Check the action log for `Reading epg2`, `Reading epg37`, `WARNING`, and `EPG source ... loaded` to identify the blocked source.

## Validation

The code passes Python compilation and the EPG 2 file fallback was tested using the provided compressed XMLTV sample. A full GitHub Actions execution and the remote 403 endpoint were not testable here.
