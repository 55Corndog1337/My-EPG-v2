#!/usr/bin/env python3
"""Overlay sports events onto the existing full guide, with a separately matched M3U guide.
Never publish the downloaded M3U or its stream URLs.
"""
import argparse,csv,gzip,os,re,urllib.request,xml.etree.ElementTree as ET
from pathlib import Path
from collections import defaultdict
from datetime import datetime,timezone
import dual_sports_epg as sports
import match_utils

CATEGORIES={'MLB':'MLB','MILB':'MILB','NBA':'NBA','MLS':'MLS','NHL':'NHL','NFL':'NFL','NCAA':'NCAA','FLO SPORTS TV':'FLO','NBA IN THE ARENA':'NBA_ARENA','NBA IN ARENA':'NBA_ARENA'}
NUM=re.compile(r'\b(?:GAME|FEED|CHANNEL|SOCCER|TV|SPORTS)?\s*0*(\d{1,4})\b',re.I)
PREFIX={'NBA_ARENA':re.compile(r'\bNBA\s+IN\s*(?:THE\s*)?ARENA\s*(?:GAME|FEED|CHANNEL)?\s*0*(\d{1,4})\b',re.I),'FLO':re.compile(r'\bFLO(?:\s*SPORTS?|\s*TV)?\s*0*(\d{1,4})\b',re.I),
        **{k:re.compile(r'\b'+k+r'\s*(?:GAME|FEED|SOCCER|CHANNEL)?\s*0*(\d{1,4})\b',re.I) for k in ('MLB','MILB','NBA','MLS','NHL','NFL','NCAA')}}

def norm(s):return re.sub(r'[^A-Z0-9]','',(s or '').upper())
def group_key(group):
    parts=[p.strip().upper() for p in (group or '').split('|')]
    tail=parts[-1] if parts else ''
    if tail in CATEGORIES:return CATEGORIES[tail]
    # Xtream group names may omit AM|USA|; accept only explicit sports category names.
    for key,canonical in CATEGORIES.items():
        if norm(tail)==norm(key):return canonical
    return None

def key_for(row,force_group=False):
    group=group_key(row['group'])
    if sports.ARENA.search(row['name']+' '+row['group']):
        group='NBA_ARENA'
    if not group and not force_group:
        # Xtream titles identify sport even when category is broader.
        for k,pat in PREFIX.items():
            if pat.search(row['name']):group=k;break
    if not group:return None
    pat=PREFIX[group];m=pat.search(row['name'])
    if not m and force_group:
        # For M3U sports categories, accept a number after a generic GAME/FEED prefix.
        m=re.search(r'\b(?:GAME|FEED|CHANNEL)\s*0*(\d{1,4})\b',row['name'],re.I)
    return (group,int(m.group(1))) if m else None

def load_m3u():
    url=os.getenv('PLAYLIST_URL','').strip()
    if not url:raise ValueError('Missing PLAYLIST_URL secret')
    if not url.startswith(('https://','http://')):raise ValueError('PLAYLIST_URL must be http(s)')
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Sports-EPG/1.0'}),timeout=120) as r:
        b=r.read(100*1024*1024+1)
    if len(b)>100*1024*1024:raise ValueError('M3U too large')
    if b[:2]==b'\x1f\x8b':b=gzip.decompress(b)
    data=b.decode('utf-8-sig','replace')
    if '#EXTINF:' not in data:raise ValueError('No EXTINF in M3U')
    return data

def parse_m3u(data):
    rows=[];lines=data.splitlines();pending=None
    for i,line in enumerate(lines):
        if line.startswith('#EXTINF:'):
            meta,sep,name=line.partition(',');attrs=dict(sports.ATTR.findall(meta))
            rows.append({'name':name.strip(),'group':attrs.get('group-title',''),'id':attrs.get('tvg-id',''),'line':i,'raw':line})
    return lines,rows

def read_xml(path):
    with gzip.open(path,'rb') if str(path).endswith('.gz') else open(path,'rb') as f:return ET.parse(f).getroot()

def write_xml(root,path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(path,'wb',compresslevel=6) as f:ET.ElementTree(root).write(f,encoding='utf-8',xml_declaration=True)

def overlay(base,generated):
    root=read_xml(base);add=read_xml(generated)
    # NHL numbered games are generated from live Xtream names in build_epg.py.
    # Never overwrite their programmes with the separate sports overlay's
    # 'No Game Today' placeholders or unrelated donor EPG listings.
    protected=set()
    try:
        with open('channels.csv',newline='',encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                if re.search(r'\\bNHL GAME\\s*0*\\d+\\b',row.get('ChannelName',''),re.I):
                    sid=(row.get('StreamID') or '').strip()
                    if sid.isdigit():protected.add('xtream.'+sid)
                    epg=(row.get('EPGID') or '').strip()
                    if epg.upper().startswith('NHL.'):protected.add(epg)
    except FileNotFoundError:
        pass
    new_ids={e.get('id') for e in add.findall('channel')} - protected
    for p in list(root.findall('programme')):
        if p.get('channel') in new_ids:root.remove(p)
    existing={c.get('id') for c in root.findall('channel')}
    for c in add.findall('channel'):
        if c.get('id') not in existing and c.get('id') not in protected:root.append(c)
    for p in add.findall('programme'):
        if p.get('channel') not in protected:root.append(p)
    return root

def epg37_regular_matches(epg37_path, m3u_rows, excluded_ids):
    """Return EPG37 programmes keyed by original playlist IDs, for safe exact/unique matches."""
    if not epg37_path:return {},[]
    import copy
    opener=gzip.open if str(epg37_path).endswith('.gz') else open
    source_ids=set();source_names=defaultdict(set)
    with opener(epg37_path,'rb') as f:
        for _,e in ET.iterparse(f,events=('end',)):
            if e.tag=='channel':
                cid=e.get('id','');source_ids.add(cid)
                for n in e.findall('display-name'):
                    if n.text:source_names[norm(n.text)].add(cid)
                e.clear()
            elif e.tag=='programme':e.clear()
    mappings={};report=[]
    for row in m3u_rows:
        cid=row['id'].strip()
        if not cid or cid in excluded_ids:continue
        if sports.exception_number(row['name'],row['group']) or sports.EVENT_FEED.search(row['name']+' '+row['group']):continue
        source=None;status=''
        if cid in source_ids:source=cid;status='EPG37_EXACT_ID'
        else:
            names=source_names.get(norm(row['name']),set())
            if len(names)==1:source=next(iter(names));status='EPG37_UNIQUE_NAME'
        if source:
            mappings[cid]=source;report.append((cid,row['name'],source,status))
    reverse=defaultdict(list)
    for target,source in mappings.items():reverse[source].append(target)
    found=defaultdict(list)
    with opener(epg37_path,'rb') as f:
        for _,e in ET.iterparse(f,events=('end',)):
            if e.tag=='programme':
                for target in reverse.get(e.get('channel',''),[]):
                    item=copy.deepcopy(e);item.set('channel',target);found[target].append(item)
                e.clear()
            elif e.tag=='channel':e.clear()
    report=[(*r,len(found[r[0]])) for r in report]
    return dict(found),report

def merge_epg37(root, programmes, protected_ids):
    available={cid for cid,items in programmes.items() if items and cid not in protected_ids}
    if not available:return 0
    for e in list(root.findall('programme')):
        if e.get('channel') in available:root.remove(e)
    known={c.get('id') for c in root.findall('channel')}
    for cid in available:
        if cid not in known:
            ch=ET.SubElement(root,'channel',{'id':cid});ET.SubElement(ch,'display-name').text=cid
        for prog in programmes[cid]:root.append(prog)
    return len(available)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--base',default='site/epg.xml.gz');ap.add_argument('--output-dir',default='site');ap.add_argument('--epg37-file');args=ap.parse_args()
    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    base=Path(args.base)
    if not base.exists():raise FileNotFoundError('Existing full guide missing: '+str(base))
    now=datetime.now(timezone.utc);exc=sports.exception_programmes({'epg37':args.epg37_file})
    xtream=list(sports.xtream_rows());m3u_lines,m3u=parse_m3u(load_m3u())
    # Keep the ORIGINAL M3U tvg-id so the user can keep using PLAYLIST_URL.
    # No stream URLs are written into public outputs or reports.
    xmap=match_utils.build_index(xtream)
    report=[];m3u_sports=[];mapped_lines=list(m3u_lines)
    seen_ids={}
    matched_keys=set()
    for target in m3u:
        # NCAAF 01-16 always use EPG37, independently of numbered Xtream matches.
        # Paramount and MAX PPV likewise use their own advertised channel titles.
        ncaaf=sports.exception_number(target['name'],target['group'])
        special=bool(sports.EVENT_FEED.search(target['name']+' '+target['group']))
        if ncaaf or special:
            if target['id'].strip():
                m3u_sports.append({'name':target['name'],'group':target['group'],
                                   'id':target['id'].strip(),'stream':''})
                report.append(['NCAAF' if ncaaf else 'EVENT',ncaaf or '',target['name'],target['id'],'EPG37' if ncaaf else 'CHANNEL_TITLE','SPECIAL_SOURCE'])
            else:
                report.append(['SPECIAL','',target['name'],'','','MISSING_TVG_ID'])
            continue
        key=match_utils.key(target)
        if key is None:continue
        source,status=match_utils.match(target,xmap)
        if source is None:
            report.append([key[0],key[1],target['name'],target['id'],'',status]);continue
        cid=target['id'].strip()
        if not cid:
            report.append([key[0],key[1],target['name'],'',source['name'],'MISSING_TVG_ID']);continue
        if cid in seen_ids and seen_ids[cid]!=key:
            report.append([key[0],key[1],target['name'],cid,source['name'],'DUPLICATE_TVG_ID']);continue
        if cid in seen_ids:
            report.append([key[0],key[1],target['name'],cid,source['name'],'DUPLICATE_CHANNEL']);continue
        seen_ids[cid]=key
        new=dict(source,id=cid,group=target['group'])
        # An Arena channel's own event takes precedence; only copy regular NBA if blank.
        if key[0]=='NBA' and key[2]=='ARENA' and sports.event(target['name'],now):
            new['name']=target['name']
            status='NBA_ARENA_OWN_LISTING'
        m3u_sports.append(new)
        matched_keys.add(match_utils.key(source))
        report.append([key[0],key[1],target['name'],cid,source['name'],status])
    for key,sources in sorted(xmap.items()):
        if key not in matched_keys:
            for source in sources:report.append([key[0],key[1],'','',source['name'],'NOT_IN_M3U'])
    # Preserve the full existing guide. Each output is full-guide data plus its own sports overlay.
    xtream_sports=out/'sports-xtream.xml.gz';m3u_sports_file=out/'sports-m3u.xml.gz'
    sports.build(xtream,xtream_sports,now,exc)
    sports.build(m3u_sports,m3u_sports_file,now,exc)
    # Add verified EPG37 regular schedules to both full guides without touching
    # the sports-event IDs generated above. This preserves ordinary base schedules
    # whenever EPG37 lacks actual programme data.
    sports_xtream_ids={c.get('id') for c in read_xml(xtream_sports).findall('channel')}
    sports_m3u_ids={c.get('id') for c in read_xml(m3u_sports_file).findall('channel')}
    epg37_programmes,epg37_report=epg37_regular_matches(args.epg37_file,m3u,sports_m3u_ids)
    xtream_root=overlay(base,xtream_sports)
    m3u_root=overlay(base,m3u_sports_file)
    merged=merge_epg37(m3u_root,epg37_programmes,sports_m3u_ids)
    write_xml(xtream_root,out/'epg-xtream.xml.gz')
    write_xml(m3u_root,out/'epg-m3u.xml.gz')
    print('EPG37 regular M3U channels with programmes:',merged)
    Path('reports').mkdir(exist_ok=True)
    with open('reports/epg37-regular-matches.csv','w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['M3U TVG ID','Channel','EPG37 ID','Match Type','Programmes']);w.writerows(epg37_report)
    Path('reports').mkdir(exist_ok=True)
    with open('reports/sports-m3u-mapping.csv','w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['Sport','Number','M3U Channel','Original M3U TVG ID','Xtream Channel','Status']);w.writerows(report)
    # The original M3U remains unchanged: no replacement playlist is needed.
    print('Created full Xtream and M3U guides. Sports mapped:',sum(r[-1].startswith('MATCHED') or r[-1].startswith('NBA_ARENA_') for r in report),'unmatched:',sum(not (r[-1].startswith('MATCHED') or r[-1].startswith('NBA_ARENA_')) for r in report))
    print('Original M3U TVG IDs retained; no replacement playlist needed.')
if __name__=='__main__':main()
