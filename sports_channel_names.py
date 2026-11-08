"""Sports display-name enrichment for build_epg.py (stdlib only).

Reads already-fetched XMLTV sources; does not download a second copy or change
stream IDs / EPG IDs. Unambiguous numbered feed identity is required.
"""
from __future__ import annotations
import csv
import io
import re
import xml.etree.ElementTree as ET
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

EAST = ZoneInfo('America/New_York')
EMPTY = 'No Game Scheduled'
LEAGUES = ('NCAAF','NCAAB','NHL','NBA','NFL','MLS','AHL','MLB','MILB')
NO_PREFIX = {'NHL','NBA','NFL','MLS','AHL','MLB','MILB'}
MONTHS = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}
PREFIX_RE = re.compile(r'^\s*(?:(?:US|USA|CA|CANADA|LIVE)\s*[-:|]\s*)+',re.I)
SLOT_RE = re.compile(r'\b(NCAAF|NCAAB|NHL|NBA|NFL|MLS(?:\s+SOCCER)?|AHL|MLB|MILB)\s*(?:PPV\s*)?(?:GAME|GAMES|EVENT|EVENTS|SOCCER|IN\s*ARENA|ARENA)?\s*[-_#.: ]*0*(\d{1,4})\b',re.I)
FLO_RE = re.compile(r'\b(?:FLO|FLSP)\s*[-_#.: ]*0*(\d{1,4})\b',re.I)
ESPN_RE = re.compile(r'\b(?:ESPN\s*\+|ESPN\s*PLUS|ESPNPLUS)\s*[-_#.: ]*0*(\d{1,4})\b',re.I)
EVENT_RE = re.compile(r'\b(?:vs\.?|versus|@| at )\b',re.I)
ISO_DATE_RE = re.compile(r'\b(20\d{2})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{2})(?::\d{2})?\b')
DATE_RE = re.compile(r'\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?\s+(\d{1,2})\b',re.I)
CLOCK_RE = re.compile(r'(?<!\w)(\d{1,2})(?::(\d{2}))?\s*(AM|PM)(?:\s*(?:ET|EST|EDT))?\b',re.I)
STOP_RE = re.compile(r'\s+(?:\d{1,2}:\d{2}\s*(?:AM|PM)\s*UK|/\s*.*)$',re.I)
PLACEHOLDER = re.compile(r'^(?:no game|no event|no information|signing off|off air|to be announced|tba|upcoming|scheduled programming|NCAAF\s*\d+\s*$)',re.I)
QUALIFIERS = re.compile(r'\b(?:HD|FHD|UHD|4K|LIVE|REPLAY)\b',re.I)

def canon(v):return re.sub(r'[^a-z0-9]','',str(v or '').casefold())
def clean(v):return re.sub(r'\s+',' ',str(v or '').strip())
def original_name(row):return (row.get('ChannelName') or '').strip()
def category(row):return (row.get('Group') or row.get('Category') or '').upper()
def number(v,kind):
    m = {'flo':FLO_RE,'espn':ESPN_RE,'league':SLOT_RE}[kind].search(v or '')
    if not m:return None
    if kind == 'league':return (m.group(1).upper().replace(' ','').replace('MLSSOCCER','MLS'),int(m.group(2)))
    return int(m.group(1))
def feed(row):
    name=original_name(row); grp=category(row)
    if re.match(r'^\s*#+',name):return ('header',None,None)
    fl=number(name,'flo') if 'FLO' in grp or re.search(r'\bFLO\b',name,re.I) else None
    if fl is not None:return ('flo',fl,None)
    en=number(name,'espn') if 'ESPN PLUS' in grp or 'ESPN+' in grp else None
    if en is not None:return ('espn',en,None)
    le=number(name,'league')
    if le:return ('league',le[1],le[0])
    return ('other',None,None)

def xml_date(v):
    m=re.match(r'(\d{14})\s*([+-]\d{4})?',v or '')
    if not m:return None
    try:
        d=datetime.strptime(m.group(1),'%Y%m%d%H%M%S')
        z=m.group(2) or '+0000';sgn=1 if z[0]=='+' else -1
        tz=timezone(sgn*timedelta(hours=int(z[1:3]),minutes=int(z[3:5])))
        return d.replace(tzinfo=tz).astimezone(EAST)
    except ValueError:return None

def display_time(d):return f'{d.strftime("%b")} {d.day} - {d.strftime("%I:%M %p").lstrip("0")} EST'

def parse_date(v,now):
    m_iso=ISO_DATE_RE.search(v or '')
    if m_iso:
        try:return datetime(*map(int,m_iso.groups()[:3]),tzinfo=EAST)
        except ValueError:return None
    m=DATE_RE.search(v or '')
    if not m:return None
    month=MONTHS[m.group(1)[:3].upper()];day=int(m.group(2));year=now.year
    try:d=datetime(year,month,day,tzinfo=EAST)
    except ValueError:return None
    if d < now-timedelta(days=180):d=d.replace(year=year+1)
    if d > now+timedelta(days=180):d=d.replace(year=year-1)
    return d

def parse_clock(v):
    m_iso=ISO_DATE_RE.search(v or '')
    if m_iso:return (int(m_iso.group(4)),int(m_iso.group(5)))
    m=CLOCK_RE.search(v or '')
    if not m:return None
    h=int(m.group(1))%12+(12 if m.group(3).upper()=='PM' else 0)
    mins=int(m.group(2) or '0')
    if mins>59:return None
    return h,mins

def is_placeholder(v):
    v=clean(v)
    return not v or bool(PLACEHOLDER.match(v))

def readable(s):
    # Title-case all-uppercase source text, retaining sports/city abbreviations.
    s=clean(s)
    if s.upper()==s:s=s.title()
    s=re.sub(r'\b(\d+)Ers\b',lambda m:m.group(1)+'ers',s)
    s=re.sub(r'\bXc\b','XC',s)
    s=re.sub(r'\bGliac\b','GLIAC',s)
    s=re.sub(r'\bMens\b',"Men's",s)
    s=re.sub(r'\bWomens\b',"Women's",s)
    s=re.sub(r'\bU(\d{2})\b',lambda m:'U'+m.group(1),s,flags=re.I)
    for abbr in ('UCLA','BYU','TCU','LSU','UT','UAB','SMU','NFL','NBA','NHL','FC','US','USA','UCF','UNC','VCU','ETSU','VMI','MLB','NCAA','AHL','MLS','UAE','U19','U15','UK'):
        s=re.sub(r'\b'+abbr+r'\b',abbr,s,flags=re.I)
    s=re.sub(r'\bVs\.?\b','vs.',s,flags=re.I)
    return s

def event_from_text(text):
    """Requires exactly one named matchup; no guessing from generic programme names."""
    text=re.sub(r'\s*:\s*NCAAB\s*\d+\s*$','',clean(text),flags=re.I)
    text=PREFIX_RE.sub('',text)
    text=re.sub(r'^\s*\(?\s*(?:FLSP|FLO|ESPN\s*PLUS|ESPN\+)\s*[-_#.: ]*\d{1,4}\s*\)?\s*\|\s*', '', text, flags=re.I)
    text=re.sub(r'^.*?\b(?:FLO|FLSP|ESPN\s*PLUS|ESPN\+|NCAAF|NCAAB|NBA|NFL|NHL|MLS|AHL|MLB|MILB)\s*(?:GAME|SOCCER|EVENT|PPV)?\s*[-_#.: ]*\d{1,4}\s*[:|\-]?\s*','',text,flags=re.I)
    text=re.sub(r'^\s*(?:(?:LIVE|CRICKET|HOCKEY|WRESTLING|TRACK|SOCCER|NCAA\s+FOOTBALL)\s*[-:]\s*)+','',text,flags=re.I)
    text=re.split(r'\s*(?:/\s*\d{1,2}:\d{2}\s*(?:AM|PM)\s*UK|\(\d{4}-\d{2}-\d{2})',text)[0]
    text=re.sub(r'\s+[–—-]\s*(?=\d{1,2}(?::\d{2})?\s*[AP]M\b)',' ',text)
    if re.search(r'\bvs\b',text,re.I):
        text=re.sub(r'\s*@\s*(?:'+'|'.join(MONTHS)+r')\w*\s+\d{1,2}\b.*$','',text,flags=re.I)
    text=re.sub(r'\s+\b(?:'+'|'.join(MONTHS)+r')\w*\s+\d{1,2}\b.*$','',text,flags=re.I)
    text=re.sub(r'\s+\d{1,2}(?::\d{2})?\s*[AP]M\s*(?:ET|EST|EDT)?\b.*$','',text,flags=re.I)
    text=re.sub(r'\s*\([^)]*\)\s*$','',text)
    text=re.sub(r'\s+_\s+(?:Women.?s?\s+)?(?:Cricket|Hockey|Soccer|Basketball|Football)\s*$','',text,flags=re.I)
    text=re.sub(r'\s+(?:Women.?s?\s+)?(?:Cricket|Hockey)\s*$','',text,flags=re.I)
    text=re.sub(r'^(?:NCAA\s*FOOTBALL|COLLEGE\s*FOOTBALL|NCAA\s*BASKETBALL|BASKETBALL|WOMEN.S\s+CRICKET|CRICKET|SOCCER|HOCKEY|FC|FOOTBALL|BASEBALL|VOLLEYBALL|WRESTLING)\s*:\s*','',text,flags=re.I)
    text=re.sub(r'^\s*(?:NCAAM|NCAAW|NCAA\s*MEN|NCAA\s*WOMEN)\s*:\s*','',text,flags=re.I)
    # For numbered NCAAF, feed labels may be "12pm Brown at Yale".
    text=re.sub(r'^\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)\s+','',text,flags=re.I)
    text=re.sub(r'\s*:\s*NCAAB\s*\d+\s*$','',text,flags=re.I)
    text=re.sub(r'\s*@\s*(?:'+'|'.join(MONTHS)+r')\w*\s+\d{1,2}\b.*$','',text,flags=re.I) if re.search(r'\bvs\.?\b',text,re.I) else text
    text=clean(text)
    parts=re.split(r'\s+(?:vs\.?|versus|@|at)\s+',text,flags=re.I)
    if len(parts)!=2:return None
    a,b=parts
    a=clean(a.strip(' :.-'));b=clean(b.strip(' :.-'))
    b=re.sub(r'\s+\d{1,2}(?::\d{2})?\s*[AP]M\s*$','',b,flags=re.I)
    if not a or not b or len(a)>90 or len(b)>90 or is_placeholder(a) or is_placeholder(b):return None
    if re.search(r'\s+[•|]\s+',a+' '+b):return None
    return (readable(a),readable(b))

def event_name_from_text(text):
    text=PREFIX_RE.sub('',clean(text))
    text=re.sub(r'^\s*\(?\s*(?:FLSP|FLO|ESPN\s*PLUS|ESPN\+)\s*[-_#.: ]*\d{1,4}\s*\)?\s*\|\s*','',text,flags=re.I)
    text=re.sub(r'^.*?\b(?:FLO|FLSP|ESPN\s*PLUS|ESPN\+)\s*[-_#.: ]*\d{1,4}\s*[:|\-]?\s*','',text,flags=re.I)
    text=re.sub(r'^(?:LIVE\s*[-:]\s*)+','',text,flags=re.I)
    text=re.sub(r'^([A-Za-z ]{3,26})\s*:\s*','',text)
    text=re.sub(r'\s*\(20\d{2}-\d{2}-\d{2}[^)]*\)\s*$','',text)
    text=re.sub(r'\s*\([^)]*\)\s*$','',text)
    text=re.sub(r'\s+[–—]\s*\d{1,2}(?::\d{2})?\s*[AP]M\b.*$','',text,flags=re.I)
    text=re.sub(r'\s*\|.*$','',text)
    text=clean(text.strip(' -_:'))
    if not text or len(text)>115 or is_placeholder(text) or re.search(r'\bvs\.?\b',text,re.I):return None
    return readable(text)

def sport_name(row,event):
    name=original_name(row).upper();group=category(row)
    if event[0]=='league':
        league=event[2]
        if league in NO_PREFIX:return ''
        return {'NCAAF':'Football','NCAAB':'Basketball'}.get(league,league)
    text=(name+' '+group)
    if re.search(r'\b(?:FC|SOCCER)\b',text):return 'FC'
    if re.search(r'\b(?:HOOPS|BASKETBALL)\b',text):return 'Basketball'
    for p,label in [('TRACK','Track and Field'),('CROSS COUNTRY','Cross Country'),('CRICKET','Cricket'),('HOCKEY','Hockey'),('VOLLEYBALL','Volleyball'),('WRESTLING','Wrestling'),('FOOTBALL','Football'),('BASEBALL','Baseball'),('SOFTBALL','Softball'),('LACROSSE','Lacrosse'),('TENNIS','Tennis'),('RUGBY','Rugby'),('GYMNASTICS','Gymnastics'),('TRACK','Track and Field')]:
        if p in text:return label
    return ''

def source_numbers(source_channels):
    index=defaultdict(set)
    for (src,cid),ch in source_channels.items():
        aliases=[cid]+[n.text or '' for n in ch.findall('display-name')]
        for alias in aliases:
            for typ in ('flo','espn','league'):
                match=number(alias,typ)
                if match is None:continue
                key=(typ,match) if typ!='league' else ('league',match[0],match[1])
                index[(src,*key)].add(cid)
    return index

def source_mapping(row,chosen,source_channels,idx):
    kind,num,league=feed(row)
    if kind not in ('flo','espn','league'):return None,'not-event-slot'
    preference='epg2' if kind in ('flo',) or league in ('NCAAF','NCAAB') else 'epg37'
    if kind=='espn':preference='epg37'
    key=(preference,kind,num) if kind!='league' else (preference,kind,league,num)
    ids=idx.get(key,set())
    epgid=(row.get('EPGID') or '').strip()
    # First match exact provider EPG ID in requested source when it corresponds to slot.
    if epgid and (preference,epgid) in source_channels:
        if epgid in ids or not ids:
            return (preference,epgid),'exact-EPG-ID'
    if len(ids)==1:return (preference,next(iter(ids))),'exact-numbered-feed'
    if len(ids)>1:return None,'ambiguous-numbered-feed'
    return None,'not-found-in-'+preference

def source_events(source_data, required, now):
    grouped=defaultdict(list)
    for src,raw in source_data.items():
        ids={x[1] for x in required if x[0]==src}
        if not ids:continue
        for _,e in ET.iterparse(io.BytesIO(raw),events=('end',)):
            if e.tag.rsplit('}',1)[-1]=='programme':
                cid=e.get('channel','')
                if cid in ids:
                    start=xml_date(e.get('start',''))
                    stop=xml_date(e.get('stop',''))
                    if start and stop and stop>=now-timedelta(hours=10) and start<=now+timedelta(days=8):
                        titles=[clean(x.text) for x in e.findall('title') if x.text]
                        if titles:grouped[(src,cid)].append((start,stop,titles[0]))
                e.clear()
            elif e.tag.rsplit('}',1)[-1]=='channel':e.clear()
    return grouped

def choose_event(row,pair,source_channels,programmes,now):
    ch=source_channels.get(pair)
    names=[n.text or '' for n in ch.findall('display-name')] if ch is not None else []
    sources=[('source-label',s) for s in names]+[('provider-label',original_name(row))]
    prog=programmes.get(pair,[])
    for st,stop,title in sorted(prog,key=lambda x:x[0]):
        if st<=now+timedelta(days=8) and stop>now:
            sources.append(('epg-programme',title))
    typ,num,league=feed(row)
    for method,s in sources:
        if is_placeholder(s):continue
        match=event_from_text(s)
        if not match and typ in ('flo','espn'):
            title=event_name_from_text(s)
            if title:match=(title,)
        if not match:continue
        date=parse_date(s,now)
        clock=parse_clock(s)
        if not clock:
            # Programme time only counts if it is a real event, not a repeating generic block.
            real_events=[(st,sp,t) for st,sp,t in prog if event_from_text(t)==match and not re.search(r'\bNCAAF\s*\d+\s*:',t,re.I)]
            if real_events:
                st=sorted(real_events,key=lambda x:x[0])[0][0]
                date=st;clock=(st.hour,st.minute)
        if date is None and league=='NCAAF' and clock is not None:
            # A numbered NCAAF football game listing without a date is usually
            # the upcoming Saturday. Explicitly mark this estimate in the audit.
            days=(5-now.weekday())%7
            date=(now+timedelta(days=days)).replace(hour=0,minute=0,second=0,microsecond=0)
            method='inferred-next-Saturday-'+method
        if date is None or clock is None:continue
        start=date.replace(hour=clock[0],minute=clock[1],second=0,microsecond=0)
        if start < now-timedelta(days=2) or start > now+timedelta(days=8):continue
        return match,start,method
    return None,None,'no-complete-dated-event'

def set_display(ch,name):
    elems=ch.findall('display-name')
    if elems:elems[0].text=name
    else:ET.SubElement(ch,'display-name').text=name

def run(catalog,channels,programmes,source_channels,source_data,chosen,reports):
    """Write per-category CSV/TXT + master report; update existing XMLTV display-name.

    Called near the end of existing build, after all sports schedule repairs and
    before the output epg.xml.gz writer. Never overwrites EPG ID.
    """
    now=datetime.now(EAST)
    idx=source_numbers(source_channels)
    mapping={}
    need=set()
    for i,row in enumerate(catalog):
        kind,_,league=feed(row)
        if kind not in ('flo','espn','league'):continue
        pair,why=source_mapping(row,chosen,source_channels,idx)
        mapping[i]=(pair,why)
        if pair:need.add(pair)
    raw_progs=source_events(source_data,need,now)
    transformed=[]
    counts=Counter()
    for i,row in enumerate(catalog):
        kind,num,league=feed(row)
        if kind=='header':continue
        rowout={k:str(v or '') for k,v in row.items()}
        rowout['OriginalChannelName']=original_name(row)
        rowout['NewChannelName']=original_name(row)
        rowout['EPGSource']='';rowout['SourceChannelID']='';rowout['MatchStatus']='UNCHANGED'
        if kind in ('flo','espn','league'):
            if league=='NCAAF' and num<=16:
                # These are permanent broadcast networks, not numbered game slots.
                rowout['MatchStatus']='NETWORK_UNCHANGED'
            else:
                pair,why=mapping.get(i,(None,'not-found'))
                rowout['NewChannelName']=EMPTY
                rowout['MatchStatus']=why
                if pair:
                    rowout['EPGSource'],rowout['SourceChannelID']=pair
                    match,start,method=choose_event(row,pair,source_channels,raw_progs,now)
                    if match:
                        sport=sport_name(row,(kind,num,league))
                        team=f'{match[0]} vs. {match[1]}' if len(match)==2 else match[0]
                        rowout['NewChannelName']=(sport+' - ' if sport else '')+team+' - '+display_time(start)
                        rowout['MatchStatus']='MATCHED_'+method
                    elif why.startswith('exact'):
                        rowout['MatchStatus']='NO_VERIFIED_DATED_GAME'
        else:
            # Team-specific placeholders need verified channel-to-schedule
            # evidence. A game elsewhere on EPG37 does not prove this feed
            # carries that game. Preserve original ID; show empty when unknown.
            if re.search(r'\b(?:NFL|NBA|NHL|MLS|AHL|MLB|MILB)\s+TEAMS?\s*[-:]\s*',original_name(row),re.I):
                rowout['NewChannelName']=EMPTY
                rowout['MatchStatus']='TEAM_CHANNEL_NO_VERIFIED_EVENT'
            else:
                rowout['MatchStatus']='UNCHANGED_NON_EVENT_CHANNEL'
        transformed.append(rowout)
        counts[rowout['MatchStatus']]+=1
    fields=list(dict.fromkeys(k for row in transformed for k in row))
    def write_csv(path,rr):
        with path.open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rr)
    export=reports/'sports-renamed'
    export.mkdir(parents=True,exist_ok=True)
    write_csv(export/'ALL_CHANNELS_Renamed.csv',transformed)
    groups=defaultdict(list)
    for row in transformed:groups[category(row)].append(row)
    for grp,rows in groups.items():
        fn=re.sub(r'[^A-Za-z0-9_-]+','_',grp).strip('_') or 'OTHER'
        write_csv(export/(fn+'.csv'),rows)
    with (export/'channel-names.txt').open('w',encoding='utf-8') as f:
        for r in transformed:
            f.write(f"{r.get('StreamID','')} | {r['NewChannelName']}\n")
    with (export/'summary.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['Status','Count']);w.writerows(sorted(counts.items()))
    # Update XMLTV channels by existing provider ID; avoid changing shared
    # source aliases used by different playlist channels.
    by_id=defaultdict(set)
    for r in transformed:
        epgid=(r.get('EPGID') or '').strip()
        if epgid and epgid in channels:
            by_id[epgid].add(r['NewChannelName'])
    changed=0
    for cid,names in by_id.items():
        if len(names)==1:
            target=next(iter(names))
            set_display(channels[cid],target)
            changed+=1
    print('Sports names: %d rows, %d XMLTV display names updated; %s' % (len(transformed),changed,dict(counts)))
    return transformed
# Provider-first channel display naming. EPG is consulted ONLY for dedicated
# NBA TEAMS / NFL TEAMS / NHL TEAMS feeds, never for event-slot names.
import os

TEAM_CHANNEL = re.compile(r'\b(NBA|NFL|NHL)\s+TEAMS?\s*[-:]\s*(.+)$', re.I)
ANY_TEAM_CHANNEL = re.compile(r'\b(?:NBA|NFL|NHL|AHL|MLS|MLB|MILB)\s+TEAMS?\s*[-:]\s*(.+)$',re.I)
PROVIDER_SLOT = re.compile(r'\b(?:FLO\s*\d+|ESPN\s*(?:PLUS|\+)\s*\d+|(?:NBA|NFL|NHL|MLS|AHL|MLB|MILB|NCAAF|NCAAB)\s*(?:SOCCER|GAME|PPV|EVENTS?)?\s*\d+)\s*:\s*(.*)$',re.I)
FLO_SPORT = re.compile(r'^(?:LIVE\s*[-:]\s*)?(CRICKET|HOCKEY|TRACK|WRESTLING|FC|SOCCER|BASKETBALL|HOOPS|FOOTBALL|BASEBALL|VOLLEYBALL|SWIMMING|RUGBY|LACROSSE|SOFTBALL|TENNIS|GYMNASTICS|MOTORSPORTS?)\s*[-:]\s*',re.I)
AFTER_SPORT = re.compile(r'\s+(WOMENS?\s+CRICKET|CRICKET|HOCKEY|SOCCER|BASKETBALL|VOLLEYBALL|WRESTLING|FOOTBALL)\s*$',re.I)
TIME_ET = re.compile(r'\b(1[0-2]|0?[1-9]):([0-5]\d)\s*(AM|PM)\s*(?:ET|EST|EDT)\b',re.I)
DATE_MONTH = re.compile(r'\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?\s+(\d{1,2})\b',re.I)
EMPTY_DETAIL = re.compile(r'^(?:V|TBA|NO GAME(?: SCHEDULED)?|NONE|OFF AIR|TBD|COMING SOON|N/?A|)$',re.I)

def provider_detail(name):
    m=PROVIDER_SLOT.search(name)
    return clean(m.group(1)) if m else None

def provider_sport(detail,kind,league):
    if kind=='league':
        return {'NCAAF':'Football','NCAAB':'Basketball'}.get(league,'')
    source=detail.upper()
    if re.search(r'\b(?:FC|SOCCER)\b',source):return 'FC'
    if re.search(r'\b(?:BASKETBALL|HOOPS)\b',source):return 'Basketball'
    if 'WOMENS CRICKET' in source:return 'Cricket'
    for pat,lab in [('CROSS COUNTRY','Cross Country'),('XC CHAMP','Cross Country'),('CRICKET','Cricket'),('HOCKEY','Hockey'),('WRESTLING','Wrestling'),('VOLLEYBALL','Volleyball'),('FOOTBALL','Football'),('BASEBALL','Baseball'),('SOFTBALL','Softball'),('SWIMMING','Swimming'),('WATER POLO','Water Polo'),('TRACK','Track and Field'),('LACROSSE','Lacrosse'),('TENNIS','Tennis'),('RUGBY','Rugby'),('GYMNASTICS','Gymnastics')]:
        if pat in source:return lab
    return ''

def clean_provider_title(detail):
    # Remove UK listings first, then date/time. Preserve event structure.
    detail=re.split(r'\s*/\s*(?:NOV|DEC|JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|\d{1,2}:\d{2}).*?\bUK\b',detail,1,flags=re.I)[0]
    detail=re.split(r'\s*/\s*',detail,1)[0]
    detail=re.sub(r'\s*[-–—]\s*\d{1,2}:\d{2}\s*[AP]M\s*(?:ET|EDT|EST)\b.*$','',detail,flags=re.I)
    detail=re.sub(r'\s+(?:'+ '|'.join(MONTHS) +r')\w*\.?\s+\d{1,2}\b.*$','',detail,flags=re.I)
    detail=re.sub(r'^\s*LIVE\s*[-:]\s*','',detail,flags=re.I)
    detail=re.sub(r'\b(?:TNF|SNF|MNF)\s+(?=[A-Z])','',detail,flags=re.I)
    return clean(detail.strip(' :-–—'))

def title_matchup(detail):
    s=clean_provider_title(detail)
    m=FLO_SPORT.match(s)
    if m:s=s[m.end():]
    s=AFTER_SPORT.sub('',s)
    s=re.sub(r'\s*\([^)]*(?:IN.ARENA|BROADCAST|FEED)[^)]*\)\s*$','',s,flags=re.I)
    parts=re.split(r'\s+(?:VS\.?|VERSUS|@)\s+',s,flags=re.I)
    if len(parts)==2 and all(clean(x) for x in parts) and all(len(x)<110 for x in parts):
        return f'{readable(parts[0])} vs. {readable(parts[1])}'
    if re.search(r'\b(?:VS\.?|VERSUS|@)\b',s,re.I):return None
    if s and len(s)<125 and not EMPTY_DETAIL.fullmatch(s):return readable(s)
    return None

def source_date(detail, now):
    m=DATE_MONTH.search(detail)
    if not m:return None
    month=MONTHS[m.group(1).upper()[:3]]
    try:
        dt=datetime(now.year,month,int(m.group(2)),tzinfo=EAST)
        if dt < now-timedelta(days=180):dt=dt.replace(year=now.year+1)
        if dt > now+timedelta(days=180):dt=dt.replace(year=now.year-1)
        return dt
    except ValueError:return None

def source_time(detail):
    m=TIME_ET.search(detail)
    if not m:return None
    hour=int(m.group(1))%12+(12 if m.group(3).upper()=='PM' else 0)
    return hour,int(m.group(2))

def source_slot_name(row,now,inferred_date=None):
    typ,num,league=feed(row)
    name=original_name(row)
    if league=='NCAAF' and num<=16:
        # Network slot e.g. NCAAF 01 : ESPN -- preserve network, NOT "No Game Scheduled".
        d=provider_detail(name)
        return clean(d) if d and not EMPTY_DETAIL.fullmatch(d) else name,'NETWORK_UNCHANGED'
    detail=provider_detail(name)
    if detail is None:return name,'NOT_NUMBERED'
    if not detail or EMPTY_DETAIL.fullmatch(detail):return EMPTY,'NO_EVENT_IN_PROVIDER_NAME'
    event=title_matchup(detail)
    if not event:return EMPTY,'NO_EVENT_IN_PROVIDER_NAME'
    date=source_date(detail,now)
    clock=source_time(detail)
    if not clock:return EMPTY,'NO_ET_TIME_IN_PROVIDER_NAME'
    status='PROVIDER_NAME'
    if date is None:
        date=inferred_date
        status='INFERRED_DATE_FROM_RUN_DAY' if date else 'DATE_NOT_IN_PROVIDER_NAME'
    if date is None:
        return EMPTY,status
    start=date.replace(hour=clock[0],minute=clock[1])
    sport=provider_sport(detail,typ,league)
    return (sport+' - ' if sport else '')+event+' - '+display_time(start),status

def epg_team_index(source_channels):
    """Exact team channel aliases only. No generic programme/league schedule mapping."""
    idx=defaultdict(set)
    for (src,cid),ch in source_channels.items():
        if src!='epg37':continue
        aliases=[cid]+[x.text or '' for x in ch.findall('display-name')]
        for a in aliases:
            # A channel identifier like nba.bostonceltics and descriptive names.
            plain=re.sub(r'\b(?:HD|FHD|UHD|4K|LIVE)\b','',a,flags=re.I)
            for league in ('NBA','NFL','NHL'):
                match=re.search(r'\b'+league+r'\s+TEAMS?\s*[-:]\s*(.+)',plain,re.I)
                if match:idx[(league,canon(match.group(1)))].add((src,cid))
                # Source ids are accepted only if they explicitly carry a team prefix.
                match=re.match(r'^'+league+r'[._-]TEAMS?[._-](.+)$',plain,re.I)
                if match:idx[(league,canon(match.group(1)))].add((src,cid))
    return idx

def team_from_row(name):
    m=TEAM_CHANNEL.search(name)
    if not m:return None
    team=re.sub(r'\b(?:HD|FHD|UHD|4K)\b.*$','',m.group(2),flags=re.I)
    return m.group(1).upper(),canon(team)

# NCAA is the one event-slot exception to provider-first naming:
# NCAAF 17+ and NCAAB use numbered EPG2 channel labels and event titles.
# NCAAF 01-16 retain their network labels verbatim.
NCAA_ALIAS = re.compile(r'(?<![A-Za-z0-9])NCAAF?B?\s*[-_.:# ]*0*(\d{1,3})(?!\d)',re.I)
NCAA_SOURCE_ID = re.compile(r'\b(NCAAF|NCAAB)\s*[-_.:# ]*0*(\d{1,3})(?!\d)',re.I)
NCAA_TIME_PREFIX = re.compile(r'^\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s+',re.I)
NCAA_TITLE_SUFFIX = re.compile(r'\s*:\s*NCAAB\s*\d+\s*$',re.I)

def ncaa_index(source_channels):
    result=defaultdict(set)
    for (src,cid),ch in source_channels.items():
        if src!='epg2':continue
        for alias in [cid]+[x.text or '' for x in ch.findall('display-name')]:
            m=NCAA_SOURCE_ID.search(alias)
            if m:
                result[(m.group(1).upper(),int(m.group(2)))].add((src,cid))
    return result

def ncaa_programme_titles(source_data, needed):
    result=defaultdict(list)
    raw=source_data.get('epg2')
    if not raw or not needed:return result
    wanted={cid for src,cid in needed if src=='epg2'}
    # Stream-parse, without materializing the entire EPG in memory.
    for _,el in ET.iterparse(io.BytesIO(raw),events=('end',)):
        if el.tag.rsplit('}',1)[-1]=='programme':
            cid=el.get('channel','')
            if cid in wanted:
                for t in el.findall('title'):
                    if t.text and t.text not in result[cid]:result[cid].append(t.text)
            el.clear()
        elif el.tag.rsplit('}',1)[-1]=='channel':el.clear()
    return result

def ncaa_event_title(raw,league):
    value=clean(raw)
    value=NCAA_TITLE_SUFFIX.sub('',value)
    value=re.sub(r'^\s*NCAAM?\s*:\s*|^\s*NCAAW\s*:\s*','',value,flags=re.I)
    value=re.sub(r'^\s*NCAAF\s*\d+\s*:\s*','',value,flags=re.I)
    value=re.sub(r'^\s*NCAAB\s*\d+\s*:\s*','',value,flags=re.I)
    # NCAA football labels have a kickoff time embedded before the teams.
    value=NCAA_TIME_PREFIX.sub('',value)
    # Strip the explicit date after the matchup, but retain @ as a team separator.
    value=re.sub(r'\s+@\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[A-Za-z]*\.?\s+\d{1,2}\s+\d{1,2}(?::\d{2})?\s*[AP]M.*$','',value,flags=re.I)
    value=re.sub(r'^\s*(?:NCAA\s+FOOTBALL|NCAA\s+BASKETBALL|COLLEGE\s+FOOTBALL)\s*:\s*','',value,flags=re.I)
    parts=re.split(r'\s+(?:vs\.?|versus|at|@)\s+',value,flags=re.I)
    if len(parts)!=2 or not all(parts):return None
    a,b=(readable(clean(x)) for x in parts)
    if not a or not b or any(len(v)>90 for v in (a,b)):return None
    if is_placeholder(a) or is_placeholder(b):return None
    return a+' vs. '+b

def ncaa_name(league,num,pairs,source_channels,titles,now):
    if not pairs:return EMPTY,'NCAA_EPG2_CHANNEL_NOT_FOUND',None
    if len(pairs)!=1:return EMPTY,'NCAA_EPG2_CHANNEL_AMBIGUOUS',None
    pair=next(iter(pairs))
    ch=source_channels[pair]
    alias=[x.text or '' for x in ch.findall('display-name')]
    # NCAAB date/time is in EPG2 programme title, not necessarily display name.
    candidates=(titles.get(pair[1],[])+alias) if league=='NCAAB' else (alias+titles.get(pair[1],[]))
    for raw in candidates:
        event=ncaa_event_title(raw,league)
        if not event:continue
        dt=parse_date(raw,now)
        clock=parse_clock(raw)
        if league=='NCAAF' and clock is None:
            prefix=NCAA_TIME_PREFIX.search(re.sub(r'^\s*NCAAF\s*\d+\s*:\s*','',raw,flags=re.I))
            if prefix:
                hour=int(prefix.group(1))%12+(12 if prefix.group(3).upper()=='pm' else 0)
                clock=(hour,int(prefix.group(2) or 0))
        if clock is None:continue
        status='NCAA_EPG2_EXPLICIT_DATE'
        if dt is None and league=='NCAAF':
            # NCAAF guide labels omit a calendar date. Infer the next Saturday,
            # and record this distinction so it is never reported as verified.
            days=(5-now.weekday())%7
            dt=(now+timedelta(days=days)).replace(hour=0,minute=0,second=0,microsecond=0)
            status='NCAAF_EPG2_SATURDAY_DATE_INFERRED'
        if dt is None:continue
        start=dt.replace(hour=clock[0],minute=clock[1],second=0,microsecond=0)
        if start < now-timedelta(hours=36) or start > now+timedelta(days=8):continue
        return ('Football' if league=='NCAAF' else 'Basketball')+' - '+event+' - '+display_time(start),status,pair
    return EMPTY,'NCAA_EPG2_NO_CURRENT_DATED_EVENT',pair

def run(catalog,channels,programmes,source_channels,source_data,chosen,reports):
    """Provider names for event feeds, EPG2 for NCAA events, EPG37 for NBA/NFL/NHL teams.

    XMLTV source guides retain their programme contents; this function changes only
    provider display names when an existing unique provider EPG ID can be found.
    """
    now=datetime.now(EAST)
    # A missing date is not a verified fact; inferred run day is labeled in audit.
    # Flo providers list slots sequentially, so keep their day rollover separate.
    flo_day=now.replace(hour=0,minute=0,second=0,microsecond=0)
    last_flo_time=None
    idx=epg_team_index(source_channels)
    college_idx=ncaa_index(source_channels)
    college_needed=set()
    for r in catalog:
        kind,num,league=feed(r)
        if kind=='league' and league in ('NCAAF','NCAAB') and not (league=='NCAAF' and num<=16):
            college_needed.update(college_idx.get((league,num),()))
    college_titles=ncaa_programme_titles(source_data,college_needed)
    needed=set()
    for r in catalog:
        team=team_from_row(original_name(r))
        if team and len(idx.get(team,()))==1:needed.update(idx[team])
    epg_progs=source_events(source_data,needed,now) if needed else {}
    output=[];stats=Counter();mapped_by_id=defaultdict(set)
    for row in catalog:
        name=original_name(row)
        kind,num,league=feed(row)
        if kind=='header':continue
        item={k:str(v or '') for k,v in row.items()}
        item.update(OriginalChannelName=name,NewChannelName=name,MatchStatus='UNCHANGED',EPGSource='',SourceChannelID='')
        team=team_from_row(name)
        if team:
            item['NewChannelName']=EMPTY
            pairs=idx.get(team,set())
            item['MatchStatus']='TEAM_EPG37_NOT_FOUND' if not pairs else ('TEAM_EPG37_AMBIGUOUS' if len(pairs)>1 else 'TEAM_EPG37_NO_SCHEDULED_MATCH')
            if len(pairs)==1:
                pair=next(iter(pairs));item['EPGSource'],item['SourceChannelID']=pair
                # Only read this exact team feed; never take games from another team or schedule.
                for start,stop,title in sorted(epg_progs.get(pair,()),key=lambda p:p[0]):
                    if stop<=now or start>now+timedelta(days=7):continue
                    match=event_from_text(title)
                    if match and len(match)==2:
                        display=f'{match[0]} vs. {match[1]} - {display_time(start)}'
                        item['NewChannelName']=display
                        item['MatchStatus']='TEAM_EPG37_VERIFIED_PROGRAMME'
                        break
        elif kind=='league' and league in ('NCAAF','NCAAB') and not (league=='NCAAF' and num<=16):
            new,status,pair=ncaa_name(league,num,college_idx.get((league,num),set()),source_channels,college_titles,now)
            item['NewChannelName']=new
            item['MatchStatus']=status
            if pair:item['EPGSource'],item['SourceChannelID']=pair
        elif kind in ('flo','espn','league'):
            detail=provider_detail(name)
            inferred=None
            if kind=='flo' and detail:
                current=source_time(detail)
                if current:
                    # Only rollover on a substantial clock reset, not provider out-of-order slots.
                    if last_flo_time is not None and (last_flo_time[0]*60+last_flo_time[1])-(current[0]*60+current[1])>600:
                        flo_day+=timedelta(days=1)
                    last_flo_time=current
                inferred=flo_day
            item['NewChannelName'],item['MatchStatus']=source_slot_name(row,now,inferred)
        elif ANY_TEAM_CHANNEL.search(name):
            # Other leagues' team channels are not in the EPG-only exception.
            item['NewChannelName']=EMPTY
            item['MatchStatus']='OTHER_TEAM_NO_PROVIDER_GAME'
        output.append(item);stats[item['MatchStatus']]+=1
        pid=item.get('EPGID','').strip()
        if pid and pid in channels:mapped_by_id[pid].add(item['NewChannelName'])
    # Keep the guide id and programme data intact. Never rename shared IDs differently.
    changed=0
    for cid,names in mapped_by_id.items():
        if len(names)==1:
            set_display(channels[cid],next(iter(names)));changed+=1
    reports=reports/'sports-renamed';reports.mkdir(parents=True,exist_ok=True)
    fields=list(dict.fromkeys(k for r in output for k in r))
    def csvfile(path,values):
        with path.open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(values)
    csvfile(reports/'ALL_CHANNELS_Renamed.csv',output)
    groups=defaultdict(list)
    for r in output:groups[category(r)].append(r)
    for cat,rows in groups.items():
        csvfile(reports/(re.sub(r'[^A-Za-z0-9_-]+','_',cat).strip('_')+'.csv'),rows)
    with (reports/'channel-names.txt').open('w',encoding='utf-8') as f:
        for r in output:f.write(f"{r.get('StreamID','')} | {r['NewChannelName']}\n")
    with (reports/'summary.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(['MatchStatus','Count']);w.writerows(stats.items())
    print('Provider-first sports names: %d channel rows; %d unique XMLTV channel display updates; %s'%(len(output),changed,dict(stats)))
    return output


def apply_provider_first_programmes(catalog, channels, programmes, reports):
    """Event slots use the fresh Xtream assignment, never unrelated XMLTV donors.

    NCAAB remains on EPG2. Other TV and team-specific channels are untouched.
    Provider assignments are not independently verified sports schedules.
    """
    now = datetime.now(EAST)
    horizon = now + timedelta(days=2)
    assigned = defaultdict(list)
    flo_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    last_flo_time = None
    for row in catalog:
        pid = (row.get('EPGID') or '').strip()
        if not pid or pid not in channels:
            continue
        kind, num, league = feed(row)
        name = original_name(row)
        if kind == 'league':
            if league == 'NCAAB' or (league == 'NCAAF' and num <= 16):
                continue
            if league not in ('NCAAF', 'NFL', 'NBA', 'MLS', 'MLB', 'MILB', 'WNBA'):
                continue
        elif kind not in ('flo', 'espn'):
            # WNBA slot labels can be absent from the generic league parser.
            if not re.search(r'\bWNBA\s*(?:GAME\s*)?0*\d+\b', name, re.I):
                continue
        detail = provider_detail(name)
        if detail is None:
            # Numbered slot without an event description.
            detail = ''
        inferred = None
        if kind == 'flo' and detail:
            clock = source_time(detail)
            if clock:
                minutes = clock[0] * 60 + clock[1]
                if last_flo_time is not None and last_flo_time - minutes > 600:
                    flo_day += timedelta(days=1)
                last_flo_time = minutes
            inferred = flo_day
        event = title_matchup(detail) if detail and not EMPTY_DETAIL.fullmatch(detail) else None
        date = source_date(detail, now) if event else None
        clock = source_time(detail) if event else None
        if date is None and kind == 'flo':
            date = inferred
        entry = None
        if event and date and clock:
            start = date.replace(hour=clock[0], minute=clock[1])
            if now - timedelta(days=2) <= start <= horizon:
                entry = (event, start, 'NFL' if league == 'NFL' else kind)
        assigned[pid].append(entry)

    replace = {}
    audit = []
    for pid, entries in assigned.items():
        # Conflicting names for the same provider EPGID cannot be assigned safely.
        if len(set(entries)) != 1:
            value = None
            status = 'CONFLICTING_PROVIDER_NAMES'
        else:
            value = entries[0]
            status = 'PROVIDER_EVENT' if value else 'NO_EVENT_IN_PROVIDER_NAME'
        new = []
        cursor = now
        if value:
            title, start, category = value
            end = start + timedelta(hours=3 if category == 'NFL' else 4)
            start_utc = start.astimezone(timezone.utc)
            end_utc = end.astimezone(timezone.utc)
            if end_utc > now:
                if start_utc > now:
                    local = start.astimezone(EAST)
                    clock_label = local.strftime('%I:%M %p').lstrip('0')
                    upcoming = f"Upcoming: {title} ({local.strftime('%A, %B')} {local.day}, {clock_label} {local.tzname()})"
                    new.append((cursor, min(start_utc, horizon), upcoming))
                if start_utc < horizon:
                    local = start.astimezone(EAST)
                    clock_label = local.strftime('%I:%M %p').lstrip('0')
                    live = f"{title} ({local.strftime('%B')} {local.day}, {clock_label} {local.tzname()})"
                    new.append((max(now, start_utc), min(end_utc, horizon), live))
                cursor = max(now, end_utc)
            else:
                status = 'EVENT_CONCLUDED'
        if value:
            if cursor < horizon:
                new.append((cursor, horizon, 'Event has Concluded'))
        else:
            new = [(now, horizon, EMPTY)]
        for start, end, title in new:
            if end <= start:
                continue
            p = ET.Element('programme', {
                'channel': pid,
                'start': start.astimezone(timezone.utc).strftime('%Y%m%d%H%M%S +0000'),
                'stop': end.astimezone(timezone.utc).strftime('%Y%m%d%H%M%S +0000')
            })
            ET.SubElement(p, 'title', {'lang':'en'}).text = readable(title)
            ET.SubElement(p, 'desc', {'lang':'en'}).text = 'Live Xtream channel assignment; not independently verified.'
            replace.setdefault(pid, []).append(p)
        audit.append((pid, status))
    if replace:
        programmes = [p for p in programmes if p.get('channel') not in replace]
        for items in replace.values():
            programmes.extend(items)
    with (reports / 'provider-first-event-status.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['EPGID', 'Status'])
        w.writerows(audit)
    print('Provider-first sports programme overrides:', len(replace), flush=True)
    return programmes
