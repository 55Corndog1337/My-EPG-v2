#!/usr/bin/env python3
"""Generate separate Xtream and M3U XMLTV sports guides, without changing stream URLs.
Only NCAA/NCAAF 01-16 may use optional epg2/epg37 source programmes.
"""
import argparse, csv, gzip, io, json, os, re, sys, urllib.request
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET
from urllib.parse import urlencode, urlsplit, urlunsplit

EAST=ZoneInfo('America/New_York')
LEAGUE=re.compile(r'\b(?:NFL|NBA|NHL|MLB|MLS|AHL|MILB|NCAA|NCAAF|NCAAB|ESPN\s*(?:\+|PLUS)|FLO(?:SPORTS)?|UFC|PGA|NASCAR|F1)\b',re.I)
REPLAY=re.compile(r'\b(?:REPLAYS?|LEAGUE\s*PASS|HIGHLIGHTS)\b',re.I)
DATE=re.compile(r'\b(JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|MAY|JUN(?:E)?|JUL(?:Y)?|AUG(?:UST)?|SEP(?:T(?:EMBER)?)?|OCT(?:OBER)?|NOV(?:EMBER)?|DEC(?:EMBER)?)\.?\s+(\d{1,2})(?:,?\s+(20\d{2}))?\s*[-,:| ]*\s*(1[0-2]|0?[1-9]):([0-5]\d)\s*(AM|PM)\s*(ET|EST|EDT)\b',re.I)
FEED=re.compile(r'\b(?:NCAA\s*[- ]*)?NCAAF\s*(?:GAME\s*)?0*(\d{1,2})\b|\bNCAA\s*(?:GAME\s*)?0*(\d{1,2})\b',re.I)
ATTR=re.compile(r'([\w-]+)="([^"]*)"')
SOURCES={'epg2':'https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg2.xml.gz','epg37':'https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg37.xml.gz'}

def exception_number(name,group):
    if re.search(r'\bNBA\b',group+' '+name,re.I): return None
    m=FEED.search(name)
    if not m:return None
    n=int(m.group(1) or m.group(2))
    return n if 1<=n<=16 else None

def protected(name,group):
    return bool(REPLAY.search(name+' '+group) or re.search(r'\bNBA\s+IN\s*(?:THE\s*)?ARENA\b',group,re.I))

def event(name,now):
    m=DATE.search(name.replace('–','-').replace('—','-'))
    if not m:return None
    detail=name[:m.start()].strip(' -:|')
    detail=re.sub(r'^(?:US|UK|CA|AM)\s*[-:|]\s*','',detail,flags=re.I)
    detail=re.sub(r'^(?:(?:ESPN\s*(?:\+|PLUS)|FLO(?:SPORTS)?|NFL|NBA|NHL|MLB|MLS|AHL|MILB|NCAA|NCAAF|NCAAB)\s*(?:GAME|FEED|CHANNEL)?\s*\d{1,4}\s*[-:|]\s*)','',detail,flags=re.I)
    detail=re.sub(r'\s+@\s+',' vs ',detail)
    if len(detail)<4 or re.search(r'\b(?:NO GAME|SIGNING OFF|TBA)\b',detail,re.I):return None
    month={'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}[m.group(1)[:3].upper()]
    year=int(m.group(3)) if m.group(3) else now.astimezone(EAST).year
    hour=int(m.group(4))%12+(12 if m.group(6).upper()=='PM' else 0)
    try: local=datetime(year,month,int(m.group(2)),hour,int(m.group(5)),tzinfo=EAST)
    except ValueError:return None
    if m.group(7).upper() in ('EST','EDT') and local.tzname()!=m.group(7).upper():return None
    start=local.astimezone(timezone.utc)
    if not m.group(3) and month==1 and now.astimezone(EAST).month==12 and start<now-timedelta(hours=5):
        local=local.replace(year=year+1);start=local.astimezone(timezone.utc)
    if start<now-timedelta(hours=5) or start>now+timedelta(days=7):return None
    return detail,start

def api(base,user,password,action):
    parts=urlsplit(base.rstrip('/'))
    if parts.scheme not in ('http','https') or not parts.netloc or parts.username or parts.password:raise ValueError('Invalid XTREAM_URL')
    url=urlunsplit((parts.scheme,parts.netloc,parts.path.rstrip('/')+'/player_api.php','',''))
    req=urllib.request.Request(url,data=urlencode({'username':user,'password':password,'action':action}).encode(),headers={'User-Agent':'My-EPG-v2/2.0'})
    with urllib.request.urlopen(req,timeout=90) as r: return json.load(r)

def xtream_rows():
    base,user,pw=(os.getenv(x,'').strip() for x in ('XTREAM_URL','XTREAM_USERNAME','XTREAM_PASSWORD'))
    if not all((base,user,pw)):raise ValueError('Missing XTREAM_URL / XTREAM_USERNAME / XTREAM_PASSWORD')
    cats={str(c['category_id']):c.get('category_name','') for c in api(base,user,pw,'get_live_categories')}
    for s in api(base,user,pw,'get_live_streams'):
        if not s.get('stream_id'):continue
        yield {'name':str(s.get('name') or ''),'group':cats.get(str(s.get('category_id')),''),'id':str(s.get('epg_channel_id') or ''),'stream':str(s['stream_id'])}

def m3u_rows(path):
    data=Path(path).read_text(encoding='utf-8-sig')
    for line in data.splitlines():
        if not line.startswith('#EXTINF:'):continue
        a=dict(ATTR.findall(line.split(',',1)[0]));name=line.split(',',1)[-1].strip()
        yield {'name':name,'group':a.get('group-title',''),'id':a.get('tvg-id',''),'stream':''}

def fmt(t):return t.strftime('%Y%m%d%H%M%S %z')
def add_prog(tv,cid,title,a,b,description=''):
    if b<=a:return
    p=ET.SubElement(tv,'programme',{'channel':cid,'start':fmt(a),'stop':fmt(b)})
    ET.SubElement(p,'title',{'lang':'en'}).text=title
    if description:ET.SubElement(p,'desc',{'lang':'en'}).text=description

def exception_programmes(source_paths):
    # Exact numbered identity only; no fuzzy or cross-league matching.
    found={}
    for source,path in source_paths.items():
        if not path:continue
        with (gzip.open(path,'rb') if str(path).endswith('.gz') else open(path,'rb')) as f:
            data=f.read()
        root=ET.fromstring(data)
        ids={}
        for ch in root.findall('channel'):
            labels=' '.join([ch.get('id','')]+[(d.text or '') for d in ch.findall('display-name')])
            n=exception_number(labels,'')
            if n:ids.setdefault(n,set()).add(ch.get('id'))
        for p in root.findall('programme'):
            cid=p.get('channel');n=next((num for num,keys in ids.items() if cid in keys and len(keys)==1),None)
            if n is not None:found.setdefault(n,[]).append((source,p))
    return found

def build(rows,path,now,exceptions):
    root=ET.Element('tv',{'generator-info-name':'My-EPG-v2-Provider-Sports'})
    horizon=now+timedelta(days=7);seen={};report=[];used={}
    for row in rows:
        name=row['name'];group=row['group']
        if not LEAGUE.search(name+' '+group):continue
        cid=(row['id'] or ('sports.'+row['stream'] if row['stream'] else ''))
        if not cid:cid='m3u.sports.'+str(len(report)+1)
        # Identical provider IDs with different channel identities cannot be represented separately in XMLTV.
        identity=(name,group)
        if cid in seen and seen[cid]!=identity:
            report.append((cid,name,group,'CONFLICTING_TVG_ID_SKIPPED'));continue
        if cid in seen:continue
        seen[cid]=identity
        ch=ET.SubElement(root,'channel',{'id':cid});ET.SubElement(ch,'display-name').text=name
        n=exception_number(name,group)
        if n:
            entries=exceptions.get(n,[])
            # Prefer epg2; fall back to epg37, only for NCAA/NCAAF 01-16.
            chosen='epg2' if any(src=='epg2' for src,_ in entries) else 'epg37'
            applied=0
            for src,p in entries:
                if src!=chosen:continue
                try:
                    start=datetime.strptime(p.get('start','')[:14],'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
                    stop=datetime.strptime(p.get('stop','')[:14],'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
                except ValueError:continue
                if stop<now or start>horizon:continue
                title=p.findtext('title') or 'NCAA Football'
                add_prog(root,cid,title,max(start,now),min(stop,horizon));applied+=1
            report.append((cid,name,group,'NCAA_SOURCE_'+str(applied) if applied else 'NCAA_SOURCE_NOT_AVAILABLE'))
            continue
        if protected(name,group):
            add_prog(root,cid,name,now,horizon)
            report.append((cid,name,group,'PRESERVED_NAME_ONLY'));continue
        ev=event(name,now)
        if ev:
            title,start=ev;stop=start+timedelta(hours=3)
            local=start.astimezone(EAST)
            if now<start:add_prog(root,cid,f'Upcoming "{title}" {local.strftime("%b.")} {local.day} ({local.strftime("%I:%M %p").lstrip("0")} {local.tzname()})',now,start)
            add_prog(root,cid,title,max(start,now),stop,'Provider-advertised event; three-hour end is estimated.')
            if stop<horizon:add_prog(root,cid,'Signing Off',max(stop,now),horizon)
            report.append((cid,name,group,'PROVIDER_EVENT'))
        else:
            add_prog(root,cid,'NO GAME TODAY',now,horizon)
            report.append((cid,name,group,'NO_DATED_EVENT'))
    path.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(path,'wb') as f:f.write(ET.tostring(root,encoding='utf-8',xml_declaration=True))
    with path.with_suffix('').with_suffix('.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['EPGID','ChannelName','Category','Status']);w.writerows(report)
    print(path,':',len(seen),'sports channels')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--m3u',help='Input playlist path')
    ap.add_argument('--output-dir',default='site')
    ap.add_argument('--epg2-file',help='Optional local epg2.xml.gz for NCAA 01-16')
    ap.add_argument('--epg37-file',help='Optional local epg37.xml.gz for NCAA 01-16')
    ap.add_argument('--xtream-only',action='store_true');ap.add_argument('--m3u-only',action='store_true')
    args=ap.parse_args()
    if args.xtream_only and args.m3u_only:ap.error('Select one input mode or neither')
    now=datetime.now(timezone.utc)
    exc=exception_programmes({'epg2':args.epg2_file,'epg37':args.epg37_file})
    out=Path(args.output_dir)
    if not args.m3u_only:build(xtream_rows(),out/'epg-xtream.xml.gz',now,exc)
    if not args.xtream_only:
        if not args.m3u:ap.error('--m3u is required to generate the M3U guide')
        build(m3u_rows(args.m3u),out/'epg-m3u.xml.gz',now,exc)
if __name__=='__main__':
    try:main()
    except Exception as e:
        print('Generation failed:',type(e).__name__,file=sys.stderr);sys.exit(1)
