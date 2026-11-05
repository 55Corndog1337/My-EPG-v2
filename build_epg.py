#!/usr/bin/env python3
"""Build a public XMLTV guide from provider IDs and curated EPG2/EPG37.
Never publishes stream URLs, credentials, or private playlists.
"""
import csv
import gzip
import io
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent
SOURCES = {'epg2': 'https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg2.xml.gz',
           'epg37': 'https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg37.xml.gz'}
MAX_DOWNLOAD = 350 * 1024 * 1024

def norm(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').casefold())

def clean_name(s):
    s = (s or '').upper()
    s = re.sub(r'\b(?:UHD|FHD|HD|SD|HEVC|H265|H264|4K|1080P|720P|50FPS|60FPS)\b', ' ', s)
    s = re.sub(r'^(?:US|USA|UK|CA|CANADA|VIP|LIVE|TV)\s*[:|\-]+\s*', '', s)
    return norm(s)

def download(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'My-EPG-v2-Expanded/1.0'})
    with urllib.request.urlopen(req, timeout=240) as resp:
        b = resp.read(MAX_DOWNLOAD + 1)
    if len(b) > MAX_DOWNLOAD:
        raise RuntimeError('EPG download exceeds safety limit')
    return gzip.decompress(b) if b[:2] == b'\x1f\x8b' else b

def rows(path):
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def source_key(s):
    return 'epg2' if 'epg2' in (s or '').lower() else 'epg37'

def clone(el):
    return ET.fromstring(ET.tostring(el, encoding='utf-8'))

def valid_time(value, cutoff):
    try:
        return datetime.strptime(value[:14], '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc) >= cutoff
    except (ValueError, TypeError):
        return False

def flo_number(name):
    """Recognize provider FLO 002 or source FLSP 002, but not event titles."""
    m = re.search(r'\b(?:FLO|FLSP)\s*[-_ ]?\s*(\d{1,4})\b', name or '', re.I)
    return int(m.group(1)) if m else None


def flo_source_index(source_channels):
    """Resolve numbered source labels every run; never assume dummy IDs persist."""
    index = defaultdict(set)
    for (source, cid), channel in source_channels.items():
        if source != 'epg2':
            continue
        for el in channel.findall('display-name'):
            if el.text and re.match(r'^\s*\(?\s*FLSP\s*[-_ ]?\s*\d{1,4}\s*\)?(?:\s|\||$)', el.text, re.I):
                index[flo_number(el.text)].add((source, cid))
    return index


def canonical_names(value):
    """Conservative aliases for broadcast feeds, without fuzzy station guesses."""
    raw = (value or '').upper()
    raw = re.sub(r'^(?:(?:US|USA|UK|CA|CANADA|VIP|LIVE|TV)\s*[:|\-]+\s*)+', '', raw)
    raw = re.sub(r'\b(?:UHD|FHD|HD|SD|HEVC|H265|H264|4K|1080P|720P|50FPS|60FPS)\b', ' ', raw)
    raw = re.sub(r'\b(?:EAST|WEST|PACIFIC)\b', lambda m: ' '+m.group(0)+' ', raw)
    base = norm(raw)
    keys = {base} if len(base) >= 5 else set()
    # Do not erase time-shift, regional, network, or station identifiers.
    stripped = re.sub(r'\b(?:CHANNEL|CH|TELEVISION)\b', ' ', raw)
    alias = norm(stripped)
    if len(alias) >= 5:
        keys.add(alias)
    return keys

def event_number(name, prefixes):
    match = re.search(r'\b(?:' + prefixes + r')\s*[-_ +#]*\s*0*(\d{1,4})\b', name or '', re.I)
    return int(match.group(1)) if match else None

def espn37_numbered_index(source_channels):
    """Match ESPN+ feed numbers exclusively from EPG37, including event labels.

    Accept e.g. 'US - ESPN PLUS 247 :' and 'ESPN+ 001 | event'.
    A feed number is only usable when it resolves to one EPG37 channel ID.
    """
    found = defaultdict(set)
    pattern = re.compile(
        r'\bESPN\s*(?:\+|PLUS)\s*[-_ #]*0*(\d{1,4})\b', re.I)
    for pair, channel in source_channels.items():
        if pair[0] != 'epg37':
            continue
        for label in [pair[1]] + [x.text or '' for x in channel.findall('display-name')]:
            match = pattern.search(label)
            if match and 1 <= int(match.group(1)) <= 600:
                found[int(match.group(1))].add(pair)
    return found


def select_unique(candidates):
    """Prefer EPG37 only if it identifies the same feed in both sources."""
    if not candidates:
        return set()
    if len(candidates) == 1:
        return set(candidates)
    # Multiple source IDs with identical spelling can still be distinct feeds.
    ids = {cid.casefold() for _, cid in candidates}
    if len(ids) == 1:
        return {sorted(candidates, key=lambda x: (x[0] != 'epg37', x[1]))[0]}
    return set(candidates)

def main():
    catalog = rows(ROOT / 'channels.csv')
    legacy = rows(ROOT / 'matches.csv')
    site = ROOT / 'site'
    site.mkdir(exist_ok=True)
    reports = ROOT / 'reports'
    reports.mkdir(exist_ok=True)

    # First index source channel IDs and display names. No fuzzy guesses.
    source_channels = {}
    by_name = defaultdict(set)
    by_alias = defaultdict(set)
    for source, url in SOURCES.items():
        print('Reading', source, flush=True)
        raw = download(os.getenv(source.upper() + '_URL', url))
        with io.BytesIO(raw) as buf:
            for _, elem in ET.iterparse(buf, events=('end',)):
                if elem.tag.rsplit('}', 1)[-1] == 'channel':
                    cid = elem.get('id', '')
                    if cid:
                        source_channels[(source, cid)] = clone(elem)
                        by_name[clean_name(cid)].add((source, cid))
                        for alias in canonical_names(cid):
                            by_alias[alias].add((source, cid))
                        for d in elem.findall('display-name'):
                            if d.text and len(clean_name(d.text)) >= 5:
                                by_name[clean_name(d.text)].add((source, cid))
                                for alias in canonical_names(d.text):
                                    by_alias[alias].add((source, cid))
                    elem.clear()
                elif elem.tag.rsplit('}', 1)[-1] == 'programme':
                    elem.clear()
    print('Source channel IDs:', len(source_channels))
    flo_index = flo_source_index(source_channels)
    print('Unique FLSP numbers in EPG2:', sum(len(v) == 1 for v in flo_index.values()))
    espn_index = espn37_numbered_index(source_channels)
    print('Unique ESPN+ numbers in EPG37:', sum(len(v) == 1 for v in espn_index.values()))
    by_source_id = defaultdict(set)
    for pair in source_channels:
        by_source_id[pair[1].casefold()].add(pair)

    # Preserve verified mappings by original playlist tvg-id, and by exact channel name.
    legacy_by_id = defaultdict(set)
    legacy_by_name = defaultdict(set)
    for r in legacy:
        pair = (source_key(r.get('source')), r.get('source_channel_id', ''))
        if pair not in source_channels:
            continue
        if r.get('original_tvg_id'):
            legacy_by_id[r['original_tvg_id'].casefold()].add(pair)
        if r.get('playlist_channel'):
            legacy_by_name[clean_name(r['playlist_channel'])].add(pair)

    # One output XMLTV channel per distinct provider EPG ID; legacy original IDs retained.
    requested = defaultdict(set)
    audit = []
    for r in catalog:
        name = r.get('ChannelName', '')
        epgid = (r.get('EPGID') or '').strip()
        key = clean_name(name)
        tvg_name = clean_name(r.get('TVGName', ''))
        if not key or name.strip().startswith('#####'):
            continue
        candidates = set()
        method = ''
        flo_num = flo_number(name) if re.search(r'FLO\s*SPORTS', r.get('Group',''), re.I) else None
        espn_num = event_number(name, r'ESPN\s*\+|ESPN\s*PLUS|ESPNPLUS') if re.search(r'ESPN\s*\+|ESPN\s*PLUS', (r.get('Group','') + ' ' + name), re.I) else None
        flo_pair = None
        if flo_num is not None and len(flo_index.get(flo_num, ())) == 1:
            flo_pair = next(iter(flo_index[flo_num]))
        if epgid:
            candidates = legacy_by_id.get(epgid.casefold(), set())
            method = 'verified mapping by provider ID'
            if len(candidates) != 1:
                candidates = by_source_id.get(epgid.casefold(), set())
                method = 'exact source ID'
        if len(candidates) != 1:
            candidates = legacy_by_name.get(key, set())
            method = 'verified mapping by channel name'
        if len(candidates) != 1 and tvg_name and len(tvg_name) >= 5:
            tvg_candidates = by_name.get(tvg_name, set())
            if len(tvg_candidates) == 1:
                candidates = tvg_candidates
                method = 'exact normalized TVG name'
        if len(candidates) != 1 and len(key) >= 5:
            name_candidates = by_name.get(key, set())
            if len(name_candidates) == 1 or not candidates:
                candidates = name_candidates
                method = 'exact normalized source name'
        if len(candidates) != 1:
            aliases = canonical_names(name) | canonical_names(r.get('TVGName', ''))
            alias_matches = set().union(*(by_alias.get(k, set()) for k in aliases)) if aliases else set()
            alias_matches = select_unique(alias_matches)
            if len(alias_matches) == 1:
                candidates = alias_matches
                method = 'exact conservative source alias'
        # Explicit numbered FloSports labels take priority over fuzzy event names.
        # Do not guess if the EPG2 FLSP number is duplicated.
        if flo_pair:
            candidates = {flo_pair}
            method = 'numbered FLO to EPG2 FLSP'
        elif flo_num is not None:
            candidates = flo_index.get(flo_num, set())
            method = 'FLSP number ambiguous' if candidates else 'FLSP number not found'
        if espn_num is not None and flo_num is None:
            # ESPN+ feeds must use EPG37, never a similarly named EPG2 feed.
            candidates = set(espn_index.get(espn_num, set()))
            method = 'numbered ESPN+ to EPG37' if len(candidates) == 1 else ('ESPN+ ambiguous in EPG37' if candidates else 'ESPN+ absent from EPG37')
        candidates = select_unique(candidates)
        suggested_source = ''
        suggested_id = ''
        if len(candidates) == 1:
            pair = next(iter(candidates))
            suggested_source, suggested_id = pair
            # For channels without an EPG ID, adding an invented ID will not make
            # TiviMate map it automatically. Keep in report, not the public guide.
            if epgid:
                requested[epgid].add(pair)
                status = 'candidate'
            else:
                status = 'matched but missing provider EPG ID'
                if flo_pair or (espn_num is not None and method == 'numbered ESPN+ to EPG37'):
                    # XMLTV source ID is useful for manual TiviMate EPG assignment,
                    # but cannot make a blank playlist tvg-id auto-associate.
                    requested[pair[1]].add(pair)
        else:
            status = 'ambiguous' if candidates else 'unmatched'
            method = ''
        audit.append({'FloNumber': ('%03d' % flo_num) if flo_num is not None else '', 'ESPNNumber': ('%03d' % espn_num) if espn_num is not None else '', 'Group': r.get('Group',''), 'ChannelName': name,
                      'StreamID': r.get('StreamID',''), 'EPGID': epgid,
                      'Status': status, 'Method': method,
                      'SuggestedSource': suggested_source,
                      'SuggestedSourceID': suggested_id,
                      'NeedsPlaylistID': 'yes' if not epgid and len(candidates) == 1 else 'no'})

    # Existing verified IDs are always retained, even if absent from the new export.
    for original_id, pairs in legacy_by_id.items():
        if len(pairs) == 1:
            for r in legacy:
                if (r.get('original_tvg_id') or '').casefold() == original_id:
                    requested[r['original_tvg_id']].update(pairs)
                    break

    # Resolve conflicts without silently publishing a wrong schedule.
    chosen = {}
    for target, pairs in requested.items():
        if len(pairs) == 1:
            chosen[target] = next(iter(pairs))
    reverse = defaultdict(list)
    for target, pair in chosen.items():
        reverse[pair].append(target)
    print('Unambiguous output IDs:', len(chosen))

    channels = {}
    programmes = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
    counts = Counter()
    # Collect current listings only, keeping memory bounded by selected channels.
    for source, url in SOURCES.items():
        raw = download(os.getenv(source.upper() + '_URL', url))
        with io.BytesIO(raw) as buf:
            for _, elem in ET.iterparse(buf, events=('end',)):
                tag = elem.tag.rsplit('}', 1)[-1]
                if tag == 'programme':
                    cid = elem.get('channel', '')
                    targets = reverse.get((source, cid), ())
                    if targets and valid_time(elem.get('stop', ''), cutoff):
                        for target in targets:
                            p = clone(elem)
                            p.set('channel', target)
                            programmes.append(p)
                            counts[target] += 1
                    elem.clear()
                elif tag == 'channel':
                    elem.clear()
    # WATE 6 fallback, when its old EPG37 mapping is stale.
    wate_ids = {r.get('original_tvg_id') for r in legacy
                if 'WATE' in (r.get('playlist_channel') or '').upper() and r.get('original_tvg_id')}
    if wate_ids and ('epg2', 'wate.us') in source_channels:
        for target in wate_ids:
            if not counts[target]:
                chosen[target] = ('epg2', 'wate.us')
                reverse[('epg2', 'wate.us')].append(target)
        # Fetch fallback programmes if needed.
        missing = [t for t in wate_ids if not counts[t]]
        if missing:
            raw = download(os.getenv('EPG2_URL', SOURCES['epg2']))
            with io.BytesIO(raw) as buf:
                for _, elem in ET.iterparse(buf, events=('end',)):
                    if elem.tag.rsplit('}', 1)[-1] == 'programme' and elem.get('channel') == 'wate.us' and valid_time(elem.get('stop',''), cutoff):
                        for target in missing:
                            p = clone(elem); p.set('channel', target)
                            programmes.append(p); counts[target] += 1
                    elem.clear()

    for target, pair in chosen.items():
        if pair in source_channels and (counts[target] or any(row['SuggestedSource'] == pair[0] and row['SuggestedSourceID'] == pair[1] and (row['FloNumber'] or row['ESPNNumber']) for row in audit)):
            ch = clone(source_channels[pair]); ch.set('id', target)
            channels[target] = ch
    # For WATE fallback, use the fallback source channel metadata.
    for target in wate_ids:
        if counts[target] and target not in channels and ('epg2','wate.us') in source_channels:
            ch = clone(source_channels[('epg2','wate.us')]); ch.set('id',target); channels[target] = ch
    programmes = [p for p in programmes if p.get('channel') in channels]
    if not channels or not programmes:
        raise RuntimeError('No current programme data found: refusing to publish empty guide')

    for row in audit:
        if row['FloNumber'] and row['SuggestedSource'] == 'epg2':
            cid = row['SuggestedSourceID']
            row['EventStatus'] = ('Active Event' if counts[row['EPGID'] or cid] else 'Matched - No Event Scheduled')
        elif row['FloNumber']:
            row['EventStatus'] = 'Unmatched'
        else:
            row['EventStatus'] = ''
    with (reports / 'flosports-status.csv').open('w', newline='', encoding='utf-8') as f:
        fields = ['FloNumber','Group','ChannelName','StreamID','EPGID','SuggestedSourceID','EventStatus','NeedsPlaylistID']
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows({k: row.get(k, '') for k in fields} for row in audit if row['FloNumber'])
    with (reports / 'missing-id-suggestions.csv').open('w', newline='', encoding='utf-8') as f:
        fields = ['Group', 'ChannelName', 'StreamID', 'SuggestedSource', 'SuggestedSourceID']
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in audit:
            if row['Status'] == 'matched but missing provider EPG ID':
                writer.writerow({field: row.get(field, '') for field in fields})
    with (reports / 'matching-report.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['FloNumber','ESPNNumber','Group','ChannelName','StreamID','EPGID','Status','Method','SuggestedSource','SuggestedSourceID','NeedsPlaylistID','EventStatus'])
        writer.writeheader(); writer.writerows(audit)
    with (reports / 'coverage.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(['EPGID','Source','SourceChannelID','Programmes'])
        for target, pair in sorted(chosen.items()):
            w.writerow([target, *pair, counts[target]])
    out = site / 'epg.xml.gz'
    with gzip.open(out, 'wb', compresslevel=6) as f:
        f.write(b'<?xml version="1.0" encoding="utf-8"?>\n<tv generator-info-name="My-EPG-v2-Expanded">\n')
        for ch in channels.values():
            f.write(ET.tostring(ch, encoding='utf-8')); f.write(b'\n')
        for p in programmes:
            f.write(ET.tostring(p, encoding='utf-8')); f.write(b'\n')
        f.write(b'</tv>\n')
    (site / '.nojekyll').touch()
    (site / 'index.html').write_text('<!doctype html><html><meta charset="utf-8"><title>My EPG</title><h1>My EPG</h1><p><a href="epg.xml.gz">Download guide</a></p></html>', encoding='utf-8')
    print('Published', len(channels), 'channels;', len(programmes), 'programmes')
    print('Matching report:', reports / 'matching-report.csv')
    print('Missing-ID suggestions:', reports / 'missing-id-suggestions.csv')

if __name__ == '__main__':
    main()
