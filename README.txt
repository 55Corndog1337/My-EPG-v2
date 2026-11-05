MY-EPG-v2 EXPANDED — USA / CANADA / UK / SPORTS

This package includes:
  build_epg.py                  updated EPG generator
  channels.csv                  11,755 selected provider channel records
  matches.csv                   2,426 existing mapping rows
  .github/workflows/update-epg.yml   12-hour GitHub Pages deployment

INSTALL:
1. Open your existing GitHub repository: 55Corndog1337/My-EPG-v2
2. Upload/replace build_epg.py, channels.csv, and matches.csv in the repository ROOT.
3. Add/replace .github/workflows/update-epg.yml (preserve folder path).
4. In Actions, select Update EPG, then Run workflow.
5. Confirm the workflow completes before changing anything in TiviMate.
6. Keep using https://55corndog1337.github.io/My-EPG-v2/epg.xml.gz

Matching reports are saved as private GitHub Actions artifacts named epg-matching-reports.
They are NOT published on GitHub Pages. They contain channel names and IDs, not credentials.

IMPORTANT LIMITATIONS:
- The CSV provider EPG ID must match TiviMate's actual playlist EPG ID to map automatically.
- Channels without EPG IDs cannot be made to ID-match simply by publishing an XMLTV guide.
- Matching is intentionally conservative; ambiguous channels are omitted rather than assigned
  incorrect schedules. No automatic fuzzy guesses are made.
- Not all channels in EPG2/EPG37 have current programme data.
- This package has been syntax checked; the live GitHub Actions build still needs to be run
  against the current upstream EPG feeds. Do not delete the previous working revision.
- Never upload private M3U streaming URLs, Xtream usernames/passwords, or backup files.
