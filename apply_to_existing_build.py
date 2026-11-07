#!/usr/bin/env python3
"""Apply a narrow, repeatable patch to the user's existing My-EPG-v2/build_epg.py.

Does not replace the generator, GitHub workflow, or publishing logic.
Run from the repository root with approved_mappings.csv beside this script.
"""
from pathlib import Path
import ast
import shutil
import sys

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / 'build_epg.py'
APPROVED = ROOT / 'approved_mappings.csv'


def replace_once(src, old, new, label):
    if old not in src:
        raise RuntimeError(f'Cannot locate the expected {label} in build_epg.py. '
                           'The repository may have changed; no changes were written.')
    if src.count(old) != 1:
        raise RuntimeError(f'Found multiple {label} locations; refusing ambiguous edits.')
    return src.replace(old, new, 1)


def patch(src):
    if 'MY_EPG_V2_APPROVED_OVERRIDE_2026' in src:
        print('Already patched; nothing to change.')
        return src
    src = replace_once(
        src,
        "           'epg37': 'https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg37.xml.gz'}",
        "           'epg37': 'https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg37.xml.gz',\n"
        "           'epg6': 'https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg6.xml.gz'}",
        'EPG source list',
    )
    src = replace_once(
        src,
        "    return 'epg2' if 'epg2' in (s or '').lower() else 'epg37'",
        "    s = (s or '').lower()\n"
        "    return 'epg6' if 'epg6' in s else ('epg2' if 'epg2' in s else 'epg37')",
        'source key helper',
    )
    src = replace_once(
        src,
        "    return bool(re.match(r'^(?:US|AM|UK|CA)(?=$|[\\s|:_-])', group, re.I))",
        "    return bool(re.match(r'^(?:US|AM|UK|CA|VIP)(?=$|[\\s|:_-])', group, re.I))",
        'regional + VIP category filter',
    )
    load_block = '''    # MY_EPG_V2_APPROVED_OVERRIDE_2026: explicit StreamID-based mappings.
    # Approval with a blank EPGID is not a playable programme mapping.
    approved_by_streamid = {}
    approved_file = ROOT / 'approved_mappings.csv'
    if approved_file.is_file():
        for approved in rows(approved_file):
            streamid = (approved.get('StreamID') or '').strip()
            source = (approved.get('PreferredSource') or '').strip().lower()
            cid = (approved.get('EPGID') or '').strip()
            if source not in ('epg2', 'epg6', 'epg37') or not cid or not streamid:
                continue
            pair = (source, cid)
            prior = approved_by_streamid.get(streamid)
            if prior is not None and prior != pair:
                raise RuntimeError('Conflicting approved mappings for StreamID ' + streamid)
            approved_by_streamid[streamid] = pair
        print('Explicit approved StreamID mappings loaded:', len(approved_by_streamid))
    else:
        print('No approved_mappings.csv present; retaining legacy matching only')
'''
    src = replace_once(
        src,
        "    legacy = rows(ROOT / 'matches.csv')\n",
        "    legacy = rows(ROOT / 'matches.csv')\n" + load_block,
        'legacy mapping load',
    )
    override_block = '''        # Approved fixed-channel mappings take priority over name heuristics.
        # Preserve the provider's output EPGID; never replace it with source ID.
        # A source ID must actually exist in the loaded XMLTV file.
        approved_pair = approved_by_streamid.get((r.get('StreamID') or '').strip())
        if approved_pair is not None:
            if approved_pair in source_channels:
                candidates = {approved_pair}
                method = 'user-approved mapping by StreamID'
            else:
                print('WARNING approved source ID absent from XMLTV for StreamID',
                      (r.get('StreamID') or '').strip())
'''
    src = replace_once(
        src,
        "        candidates = select_unique(candidates)\n        suggested_source = ''",
        override_block + "        candidates = select_unique(candidates)\n        suggested_source = ''",
        'candidate-selection finalization',
    )
    ast.parse(src, filename='build_epg.py')
    return src


def main():
    if not TARGET.is_file():
        sys.exit('Place apply_to_existing_build.py in the existing repository root beside build_epg.py')
    if not APPROVED.is_file():
        sys.exit('Place approved_mappings.csv beside build_epg.py before patching')
    old = TARGET.read_text(encoding='utf-8-sig')
    new = patch(old)
    if new == old:
        return
    shutil.copy2(TARGET, ROOT / 'build_epg.py.before_epg6_backup')
    TARGET.write_text(new, encoding='utf-8')
    print('Updated existing build_epg.py. Backup: build_epg.py.before_epg6_backup')
    print('Your existing workflow, Xtream refresh, TiviMate output IDs and sports logic are untouched.')

if __name__ == '__main__':
    main()
