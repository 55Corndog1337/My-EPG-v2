"""Match IPTV sports by category/feed number without exposing stream URLs."""
import re
from collections import defaultdict
GROUPS={'MLB':'MLB','MILB':'MILB','NBA':'NBA','MLS':'MLS','NHL':'NHL','NFL':'NFL','NCAA':'NCAA','FLO SPORTS TV':'FLO','ESPN PLUS':'ESPN_PLUS'}
PATTERNS={
 'FLO':r'\bFLO\s*0*(\d{1,4})\b',
 'ESPN_PLUS':r'\bESPN\s*(?:PLUS|\+)\s*0*(\d{1,4})\b',
 'NCAA':r'\b(?:NCAAF|NCAA)\s*(?:GAME|FEED)?\s*0*(\d{1,4})\b',
 'MLS':r'\bMLS\s*(?:SOCCER|GAME)?\s*0*(\d{1,4})\b',
 'MILB':r'\bMILB\s*(?:GAME)?\s*0*(\d{1,4})\b',
 **{k:rf'\b{k}\s*(?:GAME|FEED)?\s*0*(\d{{1,4}})\b' for k in ('MLB','NBA','NHL','NFL')}
}
COMPILED={k:re.compile(v,re.I) for k,v in PATTERNS.items()}
ARENA=re.compile(r'\b(?:NBA\s+IN\s*(?:THE\s*)?ARENA|NBA\s+ARENA|\bIN.ARENA\b)',re.I)

def key(row):
 name=row.get('name',''); group=row.get('group','')
 tail=group.split('|')[-1].strip().upper()
 cat=GROUPS.get(tail)
 if not cat:
  for k,p in COMPILED.items():
   if p.search(name):cat=k;break
 if not cat:return None
 m=COMPILED[cat].search(name)
 if not m:return None
 kind='ARENA' if cat=='NBA' and ARENA.search(name+' '+group) else 'GAME'
 return (cat,int(m.group(1)),kind)

def build_index(rows):
 d=defaultdict(list)
 for row in rows:
  k=key(row)
  if k:d[k].append(row)
 return d

def normalize_event(name):
 s=re.split(r'\s(?:NOV|DEC|JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT)\s+\d{1,2}\b|\s[–—]\s+\d{1,2}:\d\d',name,1,flags=re.I)[0]
 s=re.sub(r'^.*?\b(?:NBA|NFL|NHL|MLB|MILB|MLS|NCAAF|NCAA|FLO|ESPN\s+PLUS)\s*(?:GAME|SOCCER)?\s*\d+\s*:\s*','',s,flags=re.I)
 return re.sub(r'[^A-Z0-9]','',s.upper())

def match(target,source_index):
 k=key(target)
 if not k:return None,'NOT_A_NUMBERED_SPORT'
 sources=source_index.get(k,[])
 if len(sources)==1:return sources[0],'MATCHED'
 if len(sources)>1:
  # Provider has US/CA/DE duplicates. Prefer the exact US channel name.
  full=[s for s in sources if s['name'].strip().upper()==target['name'].strip().upper()]
  if len(full)==1:return full[0],'MATCHED_EXACT'
  if full:sources=full
  us=[s for s in sources if s['name'].upper().startswith('US - ')]
  if len(us)==1:return us[0],'MATCHED_US'
  if us:sources=us
  norm=normalize_event(target['name']); exact=[s for s in sources if norm and norm==normalize_event(s['name'])]
  if len(exact)==1:return exact[0],'MATCHED_EVENT'
  return None,'AMBIGUOUS_SOURCE'
 if k[0]=='NBA' and k[2]=='ARENA':
  regular=source_index.get(('NBA',k[1],'GAME'),[])
  if len(regular)==1:return regular[0],'NBA_ARENA_FALLBACK'
 return None,'NOT_IN_XTREAM'
