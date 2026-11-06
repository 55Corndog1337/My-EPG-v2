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
LEAGUE=re.compile(r'\b(?:NFL|NBA|NHL|MLB|MLS|AHL|MILB|WNBA|NCAA|NCAAF|NCAAB|ESPN\s*(?:\+|PLUS)|FLO(?:\s*SPORTS?|\s*0*\d{1,4})|UFC|PGA|NASCAR|F1)\b',re.I)
EVENT_FEED=re.compile(r'\b(?:PARAMOUNT\s*\+?|MAX\s*PPV)\s*0*(\d{1,3})\b',re.I)
REPLAY=re.compile(r'\b(?:REPLAYS?|LEAGUE\s*PASS|HIGHLIGHTS)\b',re.I)
# Provider titles commonly end in "NOV 6 – 7:00 PM ET / 12:00 AM UK".
# Capture the FIRST Eastern date/time, ignoring the UK conversion.
TIME_ONLY=re.compile(r'(?<!\d)(1[0-2]|0?[1-9]):([0-5]\d)\s*(AM|PM)\s*(ET|EST|EDT)\b',re.I)
DATE=re.compile(r'\b(JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|MAY|JUN(?:E)?|JUL(?:Y)?|AUG(?:UST)?|SEP(?:T(?:EMBER)?)?|OCT(?:OBER)?|NOV(?:EMBER)?|DEC(?:EMBER)?)\.?\s+(\d{1,2})(?:,?\s+(20\d{2}))?\s*(?:[–—-]\s*)?(?:[,|:]\s*)?(1[0-2]|0?[1-9]):([0-5]\d)\s*(AM|PM)\s*(ET|EST|EDT)\b',re.I)

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
    return bool(REPLAY.search(name+' '+group))

ARENA=re.compile(r'\bNBA\s+IN\s*(?:THE\s*)?ARENA\b',re.I)
NBA_NUMBER=re.compile(r'\bNBA\s*(?:GAME|FEED|CHANNEL)?\s*0*(\d{1,4})\b',re.I)
ARENA_NUMBER=re.compile(r'\bNBA\s+IN\s*(?:THE\s*)?ARENA\s*(?:GAME|FEED|CHANNEL)?\s*0*(\d{1,4})\b',re.I)

def nba_number(name,group,arena=False):
    text=name+' '+group
    m=(ARENA_NUMBER if arena else NBA_NUMBER).search(name)
    if not m:m=(ARENA_NUMBER if arena else NBA_NUMBER).search(group)
    return int(m.group(1)) if m else None

def nba_event_signature(ev):
    if not ev:return None
    return (re.sub(r'[^a-z0-9]+','',ev[0].lower()),ev[1])

ACRONYMS={'NCAA','NCAAF','NCAAB','NFL','NBA','NHL','MLB','MLS','MiLB','AHL','UFC','ESPN','ESPN2','ESPNU','FS1','FS2','CBS','ABC','NBC','FOX','TNT','USA','USC','UCLA','BYU','TCU','UCONN','FBS','FCS','PPV','WNBA','NASCAR','F1','TV','HD','FHD','4K','UK','ET','EST','EDT','ACC','SEC','UCF','LSU','NY','LA'}
def pretty_title(title):
    """Normalize shout-case event names without altering matching identifiers."""
    def word(m):
        raw=m.group(0)
        if raw.upper() in ('VS','VERSUS'):return 'vs.'
        if raw.upper() in ACRONYMS:return raw.upper() if raw.upper()!='M I L B' else 'MiLB'
        if raw.isupper():return raw.capitalize()
        return raw
    # Preserve already naturally cased words; correct only uppercase words.
    title=re.sub(r"[A-Za-z][A-Za-z0-9']*",word,title)
    title=re.sub(r'\bvs\.*(?=\s|$)', 'vs.',title,flags=re.I)
    return title.strip()

def neutral_name(name):
    m=re.search(r'\bPARAMOUNT\s*\+?\s*0*(\d+)\b',name,re.I)
    if m:return 'Paramount '+m.group(1).zfill(2)
    m=re.search(r'\bMAX\s*PPV\s*0*(\d+)\b',name,re.I)
    if m:return 'MAX PPV '+m.group(1).zfill(2)
    return pretty_title(name)

def upcoming_description(title,start):
    if start is None:return title+' — date not available'
    local=start.astimezone(EAST)
    return title+' — '+local.strftime('%b')+' '+str(local.day)+', '+local.strftime('%I:%M %p').lstrip('0')+' '+local.tzname()

def event(name,now):
    # Always use the provider's channel title; never infer a matchup from a feed number.
    m=DATE.search(name)
    has_date=bool(m)
    if not m:m=TIME_ONLY.search(name)
    if not m:return None
    detail=name[:m.start()].strip(' -:|–—')
    # Channel prefixes such as "US - ESPN PLUS 03 :" or "US - NBA GAME 01 :"
    # are metadata, not part of the programme title.
    detail=re.sub(r'^(?:US|UK|CA|AM)\s*[-:|]\s*','',detail,flags=re.I)
    detail=re.sub(r'^(?:PARAMOUNT\s*\+?|MAX\s*PPV)\s*0*\d{1,3}\s*[-:|]\s*','',detail,flags=re.I)
    detail=re.sub(r'^NBA\s+IN\s*(?:THE\s*)?ARENA\s*(?:GAME|FEED|CHANNEL)?\s*0*\d{1,4}\s*[-:|]\s*','',detail,flags=re.I)
    detail=re.sub(r'^(?:ESPN\s*(?:\+|PLUS)|FLO(?:\s*SPORTS?|\s*0*\d{1,4})|NFL|NBA|NHL|MLB|MLS|AHL|MILB|WNBA|NCAA|NCAAF|NCAAB)\s*(?:GAME|FEED|CHANNEL|SOCCER|EVENTS?)?\s*0*\d{1,4}\s*[-:|]\s*','',detail,flags=re.I)
    detail=detail.strip(' -:|–—')
    # Preserve @ or vs and original team spelling in provider names.
    if len(detail)<4 or re.search(r'\b(?:NO GAME|SIGNING OFF|TBA)\b',detail,re.I):return None
    if not has_date:
        # Time alone is NOT sufficient to schedule a game on today's date.
        return pretty_title(detail),None
    month={'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}[m.group(1)[:3].upper()]
    year=int(m.group(3)) if m.group(3) else now.astimezone(EAST).year
    hour=int(m.group(4))%12+(12 if m.group(6).upper()=='PM' else 0)
    try: local=datetime(year,month,int(m.group(2)),hour,int(m.group(5)),tzinfo=EAST)
    except ValueError:return None
    if m.group(7).upper() in ('EST','EDT') and local.tzname()!=m.group(7).upper():return None
    start=local.astimezone(timezone.utc)
    # Yearless provider listings can straddle New Year's Day.
    if not m.group(3) and month==1 and now.astimezone(EAST).month==12:
        local=local.replace(year=year+1);start=local.astimezone(timezone.utc)
    if not m.group(3) and month==12 and now.astimezone(EAST).month==1:
        local=local.replace(year=year-1);start=local.astimezone(timezone.utc)
    if start<now-timedelta(hours=5) or start>now+timedelta(days=7):return None
    return pretty_title(detail),start

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

# Network assignments are derived from NCAAF 01-16 names, not individual games.
NETWORKS={1:'ESPN',2:'ESPN2',3:'ESPNU',4:'ABC',5:'CBS',6:'FOX',7:'NBC',8:'ACCNetwork',9:'BigTen',10:'BigTen2',11:'SECNetwork',12:'CBSSportsNetwork',13:'FS1',14:'CW',15:'TNT',16:'USA'}
NETWORK_IDS={
 'ESPN':['ESPN.us12','ESPN(ESPN).us1'],
 'ESPN2':['ESPN2.us12','ESPN2(ESPN2).us1'],
 'ESPNU':['ESPNU.us12','ESPNU(ESPNU).us1'],
 'ABC':['ABCWABC.us12','ABCWCVB-East.ca'],
 'CBS':['CBSWCBS.us12','CBSKTVT.us12'],
 'FOX':['FOXWNYW.us12','FOXKTVU.us12'],
 'NBC':['NBCWNBC.us12','NBCWRC.us12'],
 'ACCNetwork':['ACCNetwork.us12','ACCNetwork(ACCSD).us1'],
 'BigTen':['BigTen.us12','BigTenNetworkHD(BIG10HD).us1'],
 'BigTen2':['BigTen2.us12','BigTenNetworkOverflow2HD(BG10O2H).us1'],
 'SECNetwork':['SECNetwork.us12','SECNetwork(SEC).us1'],
 'CBSSportsNetwork':['CBSSportsNetwork.us12','CBSSportsNetwork(CBSSN).us1'],
 'FS1':['FoxSports1.us12','FS1(FS1).us1'],
 'CW':['CWWLVI.us12','CWKIAH.us12'],
 'TNT':['TNT.us12'],
 'USA':['USANetwork.us12']}
FOOTBALL=re.compile(r'\b(?:college football|ncaa football|ncaaf|cfb|football championship subdivision|fbs football|fcs football|college football playoff|cfp|bowl game|bowl presented|bowl:|bowl \(|football:|football -|college gameday|big noon kickoff|sec nation|college football live|college football final)\b',re.I)
EXCLUDE=re.compile(r'\b(?:nfl|nba|basketball|soccer|volleyball|baseball|softball|hockey|rugby|high school football|hs football)\b',re.I)
MATCHUP=re.compile(r'\b(?:vs\.?|versus| at | @ )\b',re.I)

def football_title(title,desc):
    if EXCLUDE.search(title):return False
    if FOOTBALL.search(title):return True
    # Only titles explicitly identifying college football are safe to include.
    return False

def xmltime(value):
    m=re.match(r'^(\d{14})(?:\s*([+-]\d{4}))?',value or '')
    if not m:return None
    offset=m.group(2) or '+0000'
    return datetime.strptime(m.group(1)+offset,'%Y%m%d%H%M%S%z').astimezone(timezone.utc)

def exception_programmes(source_paths):
    # Read all EPG37 network schedules; epg2 is intentionally not used for NCAAF.
    path=source_paths.get('epg37')
    if not path:return {}
    wanted={cid for group in NETWORK_IDS.values() for cid in group}
    schedule={}
    opener=gzip.open if str(path).endswith('.gz') else open
    with opener(path,'rb') as f:
        for _,elem in ET.iterparse(f,events=('end',)):
            if elem.tag=='programme':
                cid=elem.get('channel','')
                if cid in wanted:
                    title=(elem.findtext('title') or '').strip()
                    desc=(elem.findtext('desc') or '').strip()
                    a=xmltime(elem.get('start'));b=xmltime(elem.get('stop'))
                    if a and b and b>a and football_title(title,desc):
                        clean=title.replace('ᴺᵉʷ','').replace('ᴿᵉᵖᵉᵃᵗ','').strip()
                        lines=[x.strip() for x in clean.splitlines() if x.strip()]
                        if len(lines)>1 and re.search(r'college football|ncaa football',lines[0],re.I):
                            clean=lines[-1]
                        schedule.setdefault(cid,[]).append((a,b,clean))
                elem.clear()
            elif elem.tag=='channel':elem.clear()
    result={}
    for number,network in NETWORKS.items():
        choices=NETWORK_IDS[network]
        # Prefer the first guide ID with football coverage, rather than mixing
        # alternate providers or accidentally doubling games.
        chosen=next((cid for cid in choices if schedule.get(cid)),None)
        result[number]=schedule.get(chosen,[]) if chosen else []
        print(f'NCAAF {number:02d} ({network}): {len(result[number])} football entries from {chosen or "NO MATCH"}')
    return result

def write_football_day(tv,cid,entries,now,horizon):
    # All qualifying broadcasts on a network, chronologically, with no overlaps.
    slots=sorted((max(a,now),min(b,horizon),title) for a,b,title in entries if b>now and a<horizon)
    cursor=now;count=0
    for a,b,title in slots:
        a=max(a,cursor)
        if b<=a:continue
        if a>cursor:
            local=a.astimezone(EAST)
            label=f'Upcoming "{title}" {local.strftime("%b")} {local.day} ({local.strftime("%I:%M %p").lstrip("0")} {local.tzname()})'
            add_prog(tv,cid,'Upcoming',cursor,a,upcoming_description(pretty_title(title),a))
        local=a.astimezone(EAST)
        add_prog(tv,cid,pretty_title(title),a,b)
        cursor=b;count+=1
    if cursor<horizon:add_prog(tv,cid,'Signing Off',cursor,horizon)
    return count

def build(rows,path,now,exceptions):
    root=ET.Element('tv',{'generator-info-name':'My-EPG-v2-Provider-Sports'})
    horizon=now+timedelta(days=7);seen={};report=[];used={}
    rows=list(rows)
    regular_nba={}
    for source in rows:
        if ARENA.search(source['name']+' '+source['group']):continue
        if not re.search(r'\bNBA\b',source['name']+' '+source['group'],re.I):continue
        number=nba_number(source['name'],source['group'])
        if number is not None:
            regular_nba.setdefault(number,[]).append(source)
    for row in rows:
        name=row['name'];group=row['group']
        if not (LEAGUE.search(name+' '+group) or EVENT_FEED.search(name+' '+group)):continue
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
            applied=write_football_day(root,cid,exceptions.get(n,[]),now,horizon)
            report.append((cid,name,group,'NCAAF_EPG37_'+str(applied) if applied else 'NCAAF_EPG37_NO_FOOTBALL'))
            continue
        if protected(name,group):
            add_prog(root,cid,name,now,horizon)
            report.append((cid,name,group,'PRESERVED_NAME_ONLY'));continue
        ev=event(name,now)
        if ARENA.search(name+' '+group):
            number=nba_number(name,group,arena=True)
            counterparts=regular_nba.get(number,[]) if number is not None else []
            if len(counterparts)==1:
                regular_event=event(counterparts[0]['name'],now)
                # An Arena listing with its own explicit matchup/time takes precedence.
                # If it has no event details, borrow the numbered NBA GAME event.
                if ev is None and regular_event is not None:
                    ev=regular_event
                    report_status='NBA_ARENA_DUPLICATED_FROM_GAME'
                elif ev is not None and nba_event_signature(ev)!=nba_event_signature(regular_event):
                    report_status='NBA_ARENA_OWN_LISTING'
                else:
                    report_status='NBA_ARENA_MATCHING_LISTING'
            else:
                report_status='NBA_ARENA_NO_UNIQUE_COUNTERPART'
        else:
            report_status='PROVIDER_EVENT'
        if ev and ev[1] is not None:
            title,start=ev;stop=start+timedelta(hours=3)
            local=start.astimezone(EAST)
            if now<start:add_prog(root,cid,'Upcoming',now,start,upcoming_description(title,start))
            add_prog(root,cid,title,max(start,now),stop,'Provider-advertised event; three-hour end is estimated. '+upcoming_description(title,start))
            if stop<horizon:add_prog(root,cid,'Signing Off',max(stop,now),horizon)
            report.append((cid,name,group,report_status))
        else:
            # An undated event remains visible, but no fictional date/time is created.
            title=ev[0] if ev else neutral_name(name)
            add_prog(root,cid,'Upcoming' if ev else neutral_name(name),now,horizon,
                     (title+' — date not available' if ev else 'No event information available.'))
            report.append((cid,name,group,'NO_DATED_EVENT'))
    path.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(path,'wb') as f:f.write(ET.tostring(root,encoding='utf-8',xml_declaration=True))
    with path.with_suffix('').with_suffix('.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['EPGID','ChannelName','Category','Status']);w.writerows(report)
    print(path,':',len(seen),'sports channels')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--m3u',help='Input playlist path')
    ap.add_argument('--m3u-url-env',default='EDITED_M3U_URL',help='Environment variable containing the private M3U URL')
    ap.add_argument('--output-dir',default='site')
    ap.add_argument('--epg2-file',help='Optional local epg2.xml.gz for NCAA 01-16')
    ap.add_argument('--epg37-file',help='Local epg37.xml.gz for NCAA 01-16')
    ap.add_argument('--xtream-only',action='store_true');ap.add_argument('--m3u-only',action='store_true')
    args=ap.parse_args()
    if args.xtream_only and args.m3u_only:ap.error('Select one input mode or neither')
    now=datetime.now(timezone.utc)
    exc=exception_programmes({'epg2':args.epg2_file,'epg37':args.epg37_file})
    out=Path(args.output_dir)
    if not args.m3u_only:build(xtream_rows(),out/'epg-xtream.xml.gz',now,exc)
    if not args.xtream_only:
        m3u_path=args.m3u
        if not m3u_path:
            secret_url=os.getenv(args.m3u_url_env,'').strip()
            if not secret_url:ap.error('Set '+args.m3u_url_env+' or pass --m3u')
            parsed=urlsplit(secret_url)
            if parsed.scheme not in ('https','http') or not parsed.netloc:ap.error('Invalid edited M3U URL')
            # Never print the private playlist URL or publish its contents.
            req=urllib.request.Request(secret_url,headers={'User-Agent':'My-EPG-v2/2.0'})
            with urllib.request.urlopen(req,timeout=120) as response:
                payload=response.read(80*1024*1024+1)
            if len(payload)>80*1024*1024:raise ValueError('Edited M3U exceeds 80 MB')
            if payload[:2]==b'\x1f\x8b':payload=gzip.decompress(payload)
            decoded=payload.decode('utf-8-sig',errors='replace')
            if '#EXTINF:' not in decoded:raise ValueError('Edited M3U has no EXTINF channel entries')
            import tempfile
            with tempfile.TemporaryDirectory() as tempdir:
                m3u_path=str(Path(tempdir)/'edited.m3u')
                Path(m3u_path).write_text(decoded,encoding='utf-8')
                build(m3u_rows(m3u_path),out/'epg-m3u.xml.gz',now,exc)
        else:
            build(m3u_rows(m3u_path),out/'epg-m3u.xml.gz',now,exc)
if __name__=='__main__':
    try:main()
    except Exception as e:
        print('Generation failed:',type(e).__name__,file=sys.stderr);sys.exit(1)
