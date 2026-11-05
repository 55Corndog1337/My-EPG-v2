# My-EPG — corrected GitHub deployment

This version uses the **previous 2,426-row matching audit** (`matches.csv`) and produces:

- Public `epg.xml.gz` via GitHub Pages
- **Private** corrected `playlist.m3u` via the workflow artifact **matching-private-playlist** (never GitHub Pages)

## Installation

1. Open https://github.com/55Corndog1337/My-EPG .
2. Upload `build_epg.py` and `matches.csv` to the **repository root** (replace existing files).
3. Replace `.github/workflows/update-epg.yml` with the version in this ZIP. **Delete the older workflow file** if it has a different name, to avoid competing scheduled runs.
4. Keep your existing `PLAYLIST_URL` GitHub Actions secret.
5. In Settings > Pages, choose **GitHub Actions** as the build source.
6. In Actions > Update EPG > Run workflow, run it and check for a green checkmark.
7. The public EPG is at https://55corndog1337.github.io/My-EPG/epg.xml.gz .
8. Open the successful Actions run and download the **matching-private-playlist** artifact. Unzip it to get `playlist.m3u` and import **that** playlist into your IPTV player. Import the public EPG URL as its guide.

## Notes

- **Do not upload** `private/playlist.m3u` to a public GitHub repository or GitHub Pages. Its URLs may contain streaming credentials.
- GitHub Actions artifacts require access to the repository; this is intentionally not a public playlist URL.
- The mapping file is a snapshot of an older playlist. Changed names/groups or ambiguous IDs may be unmatched. Check the build log's mapping counts.
- This version does not invent program data for the 142 previously unmatched channels. A match in the CSV does not guarantee current listings.
- GitHub Pages refreshes the guide every 12 hours when scheduled workflows run successfully; schedule execution can be delayed.
- The playlist must be downloaded again after channel mappings change. The EPG URL itself updates automatically.
