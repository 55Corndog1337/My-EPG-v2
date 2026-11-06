#!/usr/bin/env python3
"""Overlay sports events onto the existing full guide, with a separately matched M3U guide.
Never publish the downloaded M3U or its stream URLs.
"""
import argparse,csv,gzip,os,re,urllib.request,xml.etree.ElementTree as ET
from pathlib import Path
from collections import defaultdict
from datetime import datetime,timezone
import dual_sports_epg as sports

CATEGORIES={'MLB':'MLB','MILB':'MILB','NBA':'NBA','MLS':'MLS','NHL':'NHL','NFL':'NFL','NCAA':'NCAA','FLO SPORTS TV':'FLO'}
NUM=re.compile(r'\b(?:GAME|FEED|CHANNEL|SOCCER|TV|SPORTS)?\s*0*(\d{1,4})\b',re.I)
PREFIX={'FLO':re.compile(r'\bFLO(?:\s*SPORTS?|\s*TV)?\s*0*(\d{1,4})\b',re.I),
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
    new_ids={e.get('id') for e in add.findall('channel')}
    # Only replace schedules for sports IDs that are actually present in the target playlist.
    for p in list(root.findall('programme')):
        if p.get('channel') in new_ids:root.remove(p)
    existing={c.get('id') for c in root.findall('channel')}
    for c in add.findall('channel'):
        if c.get('id') not in existing:root.append(c)
    for p in add.findall('programme'):root.append(p)
    return root

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--base',default='site/epg.xml.gz');ap.add_argument('--output-dir',default='site');ap.add_argument('--epg37-file');args=ap.parse_args()
    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    base=Path(args.base)
    if not base.exists():raise FileNotFoundError('Existing full guide missing: '+str(base))
    now=datetime.now(timezone.utc);exc=sports.exception_programmes({'epg37':args.epg37_file})
    xtream=list(sports.xtream_rows());m3u_lines,m3u=parse_m3u(load_m3u())
    # Use exact sport + channel number. Duplicates are ambiguous and deliberately not mapped.
    xmap=defaultdict(list)
    for row in xtream:
        k=key_for(row)
        if k:xmap[k].append(row)
    mmap=defaultdict(list)
    for row in m3u:
        k=key_for(row,True)
        if k:mmap[k].append(row)
    report=[];m3u_sports=[];mapped_lines=list(m3u_lines)
    for key,targets in sorted(mmap.items()):
        matches=xmap.get(key,[])
        if len(matches)!=1 or len(targets)!=1:
            for t in targets:report.append([key[0],key[1],t['name'],'', 'UNMATCHED_OR_AMBIGUOUS'])
            continue
        source=matches[0];target=targets[0]
        # Give each sports stream a stable unique ID, even if the original playlist lacks one.
        cid='sports.'+key[0].lower()+'.'+str(key[1]).zfill(3)
        new=dict(source,id=cid,group=target['group'])
        m3u_sports.append(new)
        line=mapped_lines[target['line']]
        if re.search(r'\btvg-id="[^"]*"',line):line=re.sub(r'\btvg-id="[^"]*"','tvg-id="'+cid+'"',line,count=1)
        else:line=line.replace(',', ' tvg-id="'+cid+'",',1)
        mapped_lines[target['line']]=line
        report.append([key[0],key[1],target['name'],source['name'],'MAPPED'])
    for key,source in sorted(xmap.items()):
        if key not in mmap:report.append([key[0],key[1],'',source[0]['name'],'NOT_IN_M3U'])
    # Preserve the full existing guide. Each output is full-guide data plus its own sports overlay.
    xtream_sports=out/'sports-xtream.xml.gz';m3u_sports_file=out/'sports-m3u.xml.gz'
    sports.build(xtream,xtream_sports,now,exc)
    sports.build(m3u_sports,m3u_sports_file,now,exc)
    write_xml(overlay(base,xtream_sports),out/'epg-xtream.xml.gz')
    write_xml(overlay(base,m3u_sports_file),out/'epg-m3u.xml.gz')
    Path('reports').mkdir(exist_ok=True)
    with open('reports/sports-m3u-mapping.csv','w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['Sport','Number','M3U Channel','Xtream Channel','Status']);w.writerows(report)
    # Private mapped playlist: needed if original M3U IDs do not match sports.* IDs.
    Path('private').mkdir(exist_ok=True)
    Path('private/playlist-sports-mapped.m3u').write_text('\n'.join(mapped_lines)+'\n',encoding='utf-8')
    print('Created full Xtream and M3U guides. Sports mapped:',sum(r[-1]=='MAPPED' for r in report),'unmatched:',sum(r[-1]!='MAPPED' for r in report))
    print('Private mapped M3U is an Actions artifact only, never committed.')
if __name__=='__main__':main()
