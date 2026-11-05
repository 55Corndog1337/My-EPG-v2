"""Build an XMLTV guide and a PRIVATE, matching M3U playlist.

Source playlist is downloaded from the PLAYLIST_URL Actions secret. Never publish
playlist.m3u: streaming URLs may contain authentication credentials.
"""
import csv
import gzip
import io
import os
from pathlib import Path
import re
import shutil
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parent
SOURCES = {
    'epg2': 'https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg2.xml.gz',
    'epg37': 'https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg37.xml.gz',
}
ATTR = re.compile(r'([\w-]+)="([^"]*)"')


def download(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'My-EPG/2.0'})
    with urllib.request.urlopen(request, timeout=240) as response:
        data = response.read(160 * 1024 * 1024 + 1)
    if len(data) > 160 * 1024 * 1024:
        raise ValueError('Download exceeds 160 MiB')
    return gzip.decompress(data) if data.startswith(b'\x1f\x8b') else data


def normalize(s):
    return re.sub(r'[^a-z0-9]+', '', s.casefold())


def read_m3u(raw):
    lines = raw.decode('utf-8-sig', 'replace').splitlines()
    if not lines or not lines[0].startswith('#EXTM3U'):
        raise ValueError('Invalid M3U playlist')
    items = []
    pending = None
    for line in lines[1:]:
        if line.startswith('#EXTINF:'):
            pending = line
        elif pending and line.strip() and not line.startswith('#'):
            meta, _, name = pending.partition(',')
            attrs = dict(ATTR.findall(meta))
            items.append({'extinf': pending, 'url': line, 'name': name.strip(),
                          'group': attrs.get('group-title', ''), 'id': attrs.get('tvg-id', '')})
            pending = None
    return lines[0], items


def main():
    playlist_url = os.environ.get('PLAYLIST_URL', '').strip()
    if not playlist_url:
        raise RuntimeError('Missing GitHub Actions secret PLAYLIST_URL')
    header, items = read_m3u(download(playlist_url))
    print('Playlist entries:', len(items))
    rows = list(csv.DictReader((ROOT / 'matches.csv').open(encoding='utf-8-sig', newline='')))
    by_pair = defaultdict(list)
    by_id = defaultdict(list)
    by_name = defaultdict(list)
    for row in rows:
        if not row['source_channel_id'] or not row['output_tvg_id']:
            continue
        by_pair[(normalize(row['group']), normalize(row['playlist_channel']))].append(row)
        by_name[normalize(row['playlist_channel'])].append(row)
        if row['original_tvg_id']:
            by_id[row['original_tvg_id'].casefold()].append(row)

    assigned = []
    counts = Counter()
    for item in items:
        # Exact group+name is safest; original ID is a fallback when uniquely mapped.
        candidates = by_pair.get((normalize(item['group']), normalize(item['name'])), [])
        method = 'group+name'
        if not candidates:
            candidates = by_name.get(normalize(item['name']), [])
            method = 'name'
        if not candidates and item['id']:
            candidates = by_id.get(item['id'].casefold(), [])
            method = 'original id'
        distinct = {(r['source'], r['source_channel_id'], r['output_tvg_id']) for r in candidates}
        if len(distinct) == 1:
            row = candidates[0]
            src = 'epg2' if 'epg2' in row['source'].lower() else 'epg37'
            assigned.append((item, src, row['source_channel_id'], item['id'].strip() or None))
            counts[method] += 1
        else:
            assigned.append((item, None, None, None))
            counts['ambiguous' if distinct else 'unmatched'] += 1
    print('Mapping methods:', dict(counts))

    # Do not modify or publish the user's original playlist.
    # Guide IDs must match the original playlist IDs exactly.
    print('Original playlist IDs retained; no replacement playlist required')
    # Retain the existing workflow artifact step without altering the playlist.
    private = ROOT / 'private'
    private.mkdir(exist_ok=True)
    with (private / 'playlist.m3u').open('w', encoding='utf-8', newline='\n') as out:
        out.write('#EXTM3U\n')
        for item in items:
            out.write(item['extinf'] + '\n' + item['url'] + '\n')
    missing_ids = sum(1 for item, src, channel, target in assigned if src and not target)
    print('Matched channels with blank original tvg-id (cannot ID-match):', missing_ids)

    selected = defaultdict(lambda: defaultdict(set))
    collisions = {}
    for item, src, channel, target in assigned:
        if src and target:
            previous = collisions.setdefault(target, (src, channel))
            if previous == (src, channel):
                selected[src][channel].add(target)
            else:
                print('WARNING conflicting original ID:', target, 'keeping', previous, 'skipping', (src, channel))
    # WATE 6: collect an EPG2 fallback without changing any other mapping.
    wate_targets = {target for item, src, channel, target in assigned
                    if src and target and normalize(item['name']) == normalize('ABC 06 KNOXVILLE (WATE)')}
    wate_mapped = bool(wate_targets)
    wate_fallback_channel = None
    wate_fallback_programs = []
    channels = {}
    programs = []
    for source, url in SOURCES.items():
        print('Downloading', source)
        xml = download(url)
        # iterparse allows freeing XML elements after selection, limiting memory use.
        stream = io.BytesIO(xml)
        for event, elem in ET.iterparse(stream, events=('end',)):
            tag = elem.tag.rsplit('}', 1)[-1]
            if tag == 'channel':
                if wate_mapped and source == 'epg2' and elem.get('id') == 'wate.us':
                    wate_fallback_channel = ET.fromstring(ET.tostring(elem, encoding='utf-8'))
                for target in selected[source].get(elem.get('id'), ()):
                    if target not in channels:
                        clone = ET.fromstring(ET.tostring(elem, encoding='utf-8'))
                        clone.set('id', target)
                        channels[target] = clone
                elem.clear()
            elif tag == 'programme':
                if wate_mapped and source == 'epg2' and elem.get('channel') == 'wate.us':
                    fallback = ET.fromstring(ET.tostring(elem, encoding='utf-8'))
                    wate_fallback_programs.append(fallback)
                for target in selected[source].get(elem.get('channel'), ()):
                    if target in channels:
                        clone = ET.fromstring(ET.tostring(elem, encoding='utf-8'))
                        clone.set('channel', target)
                        programs.append(clone)
                elem.clear()
        print('Processed', source)
    for wate_target in sorted(wate_targets):
        wate_primary_count = sum(p.get('channel') == wate_target for p in programs)
        if wate_target not in channels or wate_primary_count == 0:
            if wate_fallback_channel is not None and wate_fallback_programs:
                fallback_channel = ET.fromstring(ET.tostring(wate_fallback_channel))
                fallback_channel.set('id', wate_target)
                channels[wate_target] = fallback_channel
                for p in wate_fallback_programs:
                    clone = ET.fromstring(ET.tostring(p))
                    clone.set('channel', wate_target)
                    programs.append(clone)
                print(f'WATE 6: EPG2 fallback {wate_target} ({len(wate_fallback_programs)} programmes)')
            else:
                print(f'WARNING WATE 6: no source listings for {wate_target}')
        else:
            print(f'WATE 6: primary guide {wate_target} ({wate_primary_count} programmes)')
    if not wate_mapped:
        print('WARNING WATE 6: no matching playlist entry with original tvg-id')

    # ESPN+ 001-191: report matching and listing coverage without changing mappings.
    espn_pattern = re.compile(r'ESPN\s*\+\s*0*(\d{1,3})(?!\d)', re.IGNORECASE)
    espn_entries = defaultdict(list)
    for item, src, source_id, target in assigned:
        match = espn_pattern.search(item['name'])
        if match and 1 <= int(match.group(1)) <= 191:
            espn_entries[int(match.group(1))].append((item, src, source_id, target))
    listing_counts = Counter(p.get('channel') for p in programs)
    missing_playlist = []
    unmapped = []
    missing_guide = []
    no_listings = []
    for number in range(1, 192):
        entries = espn_entries.get(number, [])
        if not entries:
            missing_playlist.append(number)
        elif not any(target for _, _, _, target in entries):
            unmapped.append(number)
        else:
            targets = {target for _, _, _, target in entries if target}
            if not any(target in channels for target in targets):
                missing_guide.append(number)
            elif not any(listing_counts[target] for target in targets):
                no_listings.append(number)
    with_listings = [number for number in range(1, 192)
                     if number in espn_entries and any(
                         target in channels and listing_counts[target] > 0
                         for _, _, _, target in espn_entries[number] if target)]
    print(f'ESPN+ 001-191: {len(espn_entries)} playlist numbers found, '
          f'{len(with_listings)} with EPG listings')
    for label, numbers in [('Not in playlist', missing_playlist),
                           ('Unmapped', unmapped),
                           ('Missing from generated EPG', missing_guide),
                           ('No programme listings', no_listings)]:
        print(f'ESPN+ {label} ({len(numbers)}): ' +
              (', '.join(f'{n:03d}' for n in numbers) if numbers else 'none'))
    if not channels or not programs:
        raise RuntimeError('No channels or programmes matched; refusing to publish')
    root = ET.Element('tv', {'generator-info-name': 'My-EPG'})
    root.extend(channels.values())
    root.extend(programs)
    site = ROOT / 'site'; site.mkdir(exist_ok=True)
    with gzip.open(site / 'epg.xml.gz', 'wb', compresslevel=6) as out:
        ET.ElementTree(root).write(out, encoding='utf-8', xml_declaration=True)
    (site / '.nojekyll').touch()
    (site / "index.html").write_text(
    """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>My IPTV EPG</title>
</head>
<body>
<h1>My IPTV EPG</h1>
<p>Automatically updated IPTV program guide.</p>
<a href="epg.xml.gz">Download EPG Guide</a>
</body>
</html>""",
    encoding="utf-8"
    )
    print("Published site files:", sorted(p.name for p in site.iterdir()))
    print('Published:', len(channels), 'channels,', len(programs), 'programmes')
    print('Original playlist IDs with EPG data:', len(channels))
    print('Original playlist unchanged; use your existing M3U with this EPG')


if __name__ == '__main__':
    main()
