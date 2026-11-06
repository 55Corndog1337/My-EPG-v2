IPTV EPG MANAGER 2.0 — WINDOWS
================================
START: Double-click matcher.pyw on Windows with Python 3.10+ installed.
TO BUILD A STANDALONE EXE: Run BUILD_WINDOWS_EXE.bat on a Windows PC with Python and internet access. The batch file installs PyInstaller and builds dist\IPTV_EPG_Manager.exe. No Windows EXE is included in this archive because this package was built in a Linux environment; Windows executable builds are not cross-compiled.

FEATURES
- M3U playlist import, Xtream Codes login, selective Xtream category import, country/category filters
- Multiple XMLTV/XML.GZ EPG sources, plus direct HTTP(S) XMLTV URLs
- Stream IDs, provider tvg-ids, EPG IDs and source columns
- EPG preview, category guide preview, missing-EPG highlighting, unmatched CSV
- Sequential numbered sports bulk matching with collision checks and undo
- Smart Match Review: indexed high-confidence suggestions; manually select and approve
- Save/Open Project: stores metadata, local paths, filters and mappings, not credentials or stream URLs
- Backup/Restore mappings: verifies playlist fingerprint to prevent wrong-order imports
- Coverage report: CSV counts for 24/48/72 hours, sampled up to first 60 programmes per EPG channel; this is NOT a complete coverage audit for long guides
- Compare EPGs: top candidates and source programme preview
- Generate combined XMLTV.GZ: copies full programme listings from approved source channels using streaming XML parsing; creates unique iptv.N channel IDs
- Export TiviMate Pair M3U: companion playlist with the same iptv.N IDs. Export BOTH the M3U copy and XMLTV.GZ for use together in TiviMate; the original playlist is not modified
- Manual Refresh Guides, optional automatic 3-hour refresh while the app is open
- Xtream provider short EPG comparison for selected channel, if the provider API supports it
- Logo URLs from IPTV playlist and XMLTV; open artwork links in browser (no embedded image viewer)

IMPORTANT LIMITATIONS
1. Automatic matching is name/ID-based, not a guarantee of correct games or live streams. Review before approving.
2. EPG previews and coverage reports hold only the first 60 programmes per channel. XMLTV export re-reads the original source and includes ALL programmes for linked channels.
3. Project files do not contain Xtream credentials or stream URLs. When reopened without the original M3U, channel metadata is restored but stream playback URLs are absent; reconnect Xtream or reload the original M3U to export a working playlist.
4. Xtream credentials are transmitted to the provider's player_api.php using its standard query interface. Use HTTPS where supported. Exported M3U files include private stream URLs; protect them.
5. XMLTV generation creates iptv.N IDs, so the matching exported M3U is REQUIRED for automatic TiviMate association. If you cannot change the playlist in TiviMate, export the CSV mappings and use your existing generator instead.
6. Automatic refresh only runs while the GUI is open. Local files are re-read; URL sources are re-downloaded. This does not upload anything to GitHub.
7. The app is Python/Tkinter; full Windows GUI and live Xtream integration have not been tested in this environment. Test on a copy of your data before relying on it.
8. Generated XMLTV contains only approved mappings. Unapproved channels in the exported M3U retain their original tvg-id and may need another EPG.
9. Country identification is heuristic; use manual category filters to refine.

TEST: python test_core.py (tests compressed XMLTV, programme streaming, sports numbering).
