# V5 EPG mapping configuration (staging)

V5 is separate from V4 and V2. This is the initial source-of-truth configuration, not a published guide. No V5 XMLTV has been generated or validated yet.

## Source priority

- NHL, NFL, NBA, MLB **team channels**: EPG 37. Never overwrite these mappings with EPG 2.
- NHL, NFL, NBA, MLB **numbered game channels**: EPG 2.
- NCAAB, NCAAF, FloSports, ESPN+, MLS, WNBA, MiLB: EPG 2.
- AHL team channels: generate from the 2026–27 AHL schedule; only map teams in Xtream inventory. Exclude nonexistent Hamilton channel. Rolling seven-day schedule; four-hour game blocks. Before: Next Game; during: Away @ Home; after: Event concluded.
- Peacock 1–100: EPG 2 IDs dummy-4817578 through dummy-4817677.
- Paramount+ 1–100: EPG 2 IDs dummy-1405347 through dummy-1405446.
- TSN+ 1–150: EPG 2 IDs dummy-3782014 through dummy-3782163 (verify exact source IDs before use).
- B1G+ 1–150 is BTN+ 1–150: EPG 2 IDs dummy-6174567 through dummy-6174716.
- ESPN+ 1–500: EPG 2 IDs dummy-3345444 through dummy-3345943; preserve existing 501–600 mappings.
- FloSports 1–800: EPG 2 IDs dummy-3769825 through dummy-3770624.
- NCAAB 1–101: EPG 2 IDs dummy-5506285 through dummy-5506385; match only channels actually present in Xtream.
- NCAAF 1–85: EPG 2 IDs dummy-26366 through dummy-26450.
- MAX PPV 1–40: EPG 2 IDs dummy-26520 through dummy-26559. Do not conflate with HBO Max On-Demand.
- Disney+ 1–5: dummy-124279 through dummy-124283; 6–15: dummy-3184725 through dummy-3184734.
- 24/7: match by movie/series title, not prefix; do not assign ambiguous IDs. Static EPG is a separate explicit option.

## Publication gates

Before enabling a V5 publishing workflow: import the full Xtream inventory and EPG 2/6/37 catalogs, reconcile the master mapping, verify programme data and IDs, and produce confirmed/suggested/unmatched reports. Preserve original Xtream StreamIDs, original channel names, and EPG IDs. Maintain EAST/WEST and static-guide settings. Do not touch V4.
