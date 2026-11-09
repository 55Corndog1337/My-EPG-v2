#!/usr/bin/env python3
"""Optional, fail-closed AI schedule enrichment for numbered Xtream sports feeds."""
import csv, json, os, re, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parent
CACHE=ROOT/"reports"/"ai-sports-events.json"
ET_ZONE=ZoneInfo("America/New_York")
LEAGUES=("ESPN+","FLO","NCAAF","NBA","MLB","WNBA","MILB","MLS","NFL")
def classify(row):
    group=(row.get("Group") or "").upper()
    name=(row.get("ChannelName") or "").upper()
    combined=group+" "+name
    if "ESPN+" in combined or "ESPN PLUS" in combined: return "ESPN+"
    if "FLOSPORT" in combined or re.search(r"\bFLO\s*0*\d+\b",name): return "FLO"
    if re.search(r"\bNCAA\s*F(?:OOTBALL)?\b|\bNCAAF\b",combined): return "NCAAF"
    for league in ("WNBA","MILB","MLS","NBA","MLB","NFL"):
        if re.search(r"\b"+league+r"\b",combined): return league
    return None
def eligible(row):
    league=classify(row)
    if not league: return None
    name=row.get("ChannelName") or ""
    m=re.search(r"\b(?:NCAAF|NCAA\s*FOOTBALL|GAME|GAMES|FLO|FLSP|ESPN\+?)\s*[-#:| ]*0*(\d{1,3})\b",name,re.I)
    if not m: return None
    number=int(m.group(1))
    if league=="NCAAF" and not 17<=number<=85: return None
    if league=="NFL" and not 1<=number<=16: return None
    if league=="NBA" and not 1<=number<=15: return None
    if league=="WNBA" and not 1<=number<=10: return None
    if league=="MILB" and not 1<=number<=70: return None
    if league=="MLS" and not 1<=number<=34: return None
    return league
def rows():
    p=ROOT/"reports"/"xtream-channels-latest.csv"
    if not p.exists(): p=ROOT/"channels.csv"
    if not p.exists(): return []
    with p.open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
def query(batch):
    key=os.getenv("OPENAI_API_KEY","")
    if not key: return []
    today=datetime.now(ET_ZONE).date().isoformat()
    instruction=("Research each numbered provider channel independently using web search. "
       "Xtream names are hints, NOT proof of time/date. Search One Page Season, official school schedules, conference schedules and bowl/playoff sources. Find independently published "
      "schedule evidence within 5 days before or 8 days after "+today+". "
      "Return ONLY a JSON array of objects with stream_id, sport, event, "
      "start_utc (ISO8601 with timezone), duration_hours (4,12,24), source_url. "
      "Return no object if unverified or ambiguous. Do not invent teams, times, "
      "events, sources, or dates. Use Away @ Home when verified. "
      "Keep all 14-day search results strictly linked to the supplied channel.")
    payload={"model":os.getenv("OPENAI_SPORTS_MODEL","gpt-4.1-mini"),
             "tools":[{"type":"web_search_preview"}],
             "input":[{"role":"developer","content":instruction},
                      {"role":"user","content":json.dumps(batch)}],
             "max_output_tokens":4500}
    req=urllib.request.Request("https://api.openai.com/v1/responses",
       data=json.dumps(payload).encode(),headers={"Authorization":"Bearer "+key,
       "Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=150) as response:
            result=json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            body=json.loads(exc.read(4096).decode("utf-8","replace"))
            err=body.get("error",{})
            code=str(err.get("code") or err.get("type") or "unknown")[:100]
            message=str(err.get("message") or "")[:300]
        except (ValueError, UnicodeError):
            code="unknown"
            message=""
        raise RuntimeError("OpenAI API HTTP "+str(exc.code)+" code="+code+" detail="+message) from None
    parts=[part.get("text","") for output in result.get("output",[])
           for part in output.get("content",[]) if part.get("type")=="output_text"]
    raw="\n".join(parts).strip()
    raw=re.sub(r"^\x60\x60\x60(?:json)?|\x60\x60\x60$","",raw).strip()
    parsed=json.loads(raw)
    return parsed if isinstance(parsed,list) else []
def validate(obj, inventory):
    if not isinstance(obj,dict):return None
    sid=str(obj.get("stream_id",""))
    if sid not in inventory:return None
    league=inventory[sid]["league"]
    sport=str(obj.get("sport","")).strip()[:50]
    event=str(obj.get("event","")).strip()[:160]
    url=str(obj.get("source_url","")).strip()
    if not sport or not event or not url.startswith("https://"):return None
    try:
        dt=datetime.fromisoformat(str(obj["start_utc"]).replace("Z","+00:00"))
        if dt.tzinfo is None:return None
        dt=dt.astimezone(timezone.utc)
        duration=int(obj.get("duration_hours",4))
        if duration not in (4,12,24):return None
        if not -timedelta(days=6)<dt-datetime.now(timezone.utc)<timedelta(days=9):return None
    except (ValueError,TypeError,KeyError):return None
    return {"stream_id":sid,"league":league,"sport":sport,"event":event,
            "start_utc":dt.isoformat(),"duration_hours":duration,"source_url":url}
def research():
    inventory={}
    for row in rows():
        league=eligible(row)
        sid=str(row.get("StreamID") or "").strip()
        if league and sid:inventory[sid]={"league":league,"name":row.get("ChannelName","")}
    old=load()
    found={x["stream_id"]:x for x in old if x.get("stream_id") in inventory}
    weekday=datetime.now(ET_ZONE).weekday()
    pending=[{"stream_id":sid,"league":v["league"],"channel_name":v["name"]}
             for sid,v in inventory.items() if v["league"]!="NCAAF" or weekday in (2,3,4,5)]
    if not os.getenv("OPENAI_API_KEY"):
        print("AI sports: no API key; retaining cached data")
        raise RuntimeError("OPENAI_API_KEY missing: AI sports research cannot run")
    success=0
    errors=0
    for start in range(0,len(pending),8):
        batch=pending[start:start+8]
        try:
            for item in query(batch):
                clean=validate(item,{k:inventory[k] for k in (x["stream_id"] for x in batch)})
                if clean:found[clean["stream_id"]]=clean;success+=1
        except Exception as exc:
            errors+=1
            print("AI sports: batch failed:",type(exc).__name__,str(exc)[:450],flush=True)
            if "OpenAI API HTTP 401" in str(exc) or "OpenAI API HTTP 402" in str(exc) or "OpenAI API HTTP 403" in str(exc) or "OpenAI API HTTP 429" in str(exc):
                print("AI sports: stopping further API requests after authentication, billing, or rate-limit error",flush=True)
                break
            if errors>=3 and success==0:
                print("AI sports: stopping after three consecutive failed batches",flush=True)
                break
    CACHE.parent.mkdir(exist_ok=True)
    tmp=CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"updated_utc":datetime.now(timezone.utc).isoformat(),
         "events":list(found.values())},indent=2)+"\n",encoding="utf-8")
    tmp.replace(CACHE)
    print("AI sports verified:",success,"of",len(pending),"candidates")
    if not success and not found:
        raise RuntimeError("AI sports research produced no verified events; inspect source names and API errors")
def load():
    try:
        obj=json.loads(CACHE.read_text(encoding="utf-8"))
        return obj.get("events",[]) if isinstance(obj,dict) else []
    except (OSError,ValueError):return []
def match_original_names(catalog, channels, programmes):
    """Match original Xtream matchup to a dated EPG or iCal event, without AI."""
    from collections import defaultdict
    import csv
    now=datetime.now(timezone.utc)
    horizon=now+timedelta(days=7)
    def normteam(v):
        return re.sub(r"[^a-z0-9]","",v.casefold())
    def teams(v):
        v=re.sub(r"^.*?\b(?:NBA|NFL|NHL|MLB|MILB|MLS|WNBA|AHL|NCAAF|NCAAB)\s*(?:GAME|GAMES)?\s*0*\d+\s*[:|\-]?\s*","",v,flags=re.I)
        m=re.search(r"([A-Za-z0-9][A-Za-z0-9 .&'/-]{1,65}?)\s+(?:@|vs\.?|versus)\s+([A-Za-z0-9][A-Za-z0-9 .&'/-]{1,65})",v,re.I)
        if not m:return None
        a,b=[x.strip(" -:|.") for x in m.groups()]
        b=re.sub(r"\s+(?:LIVE|HD|FHD|UHD|4K)$","",b,flags=re.I).strip()
        return (normteam(a),normteam(b)) if len(a)>1 and len(b)>1 else None
    def dated(v):
        try:
            d=datetime.fromisoformat(v.replace("Z","+00:00"))
            return d.astimezone(timezone.utc) if d.tzinfo else None
        except (ValueError,TypeError,AttributeError):return None
    def xmltime(v):
        try:
            m=re.match(r"^(\d{14})(?:\s*([+-]\d{4}))?",v or "")
            if not m:return None
            d=datetime.strptime(m.group(1),"%Y%m%d%H%M%S")
            z=m.group(2)
            if z:
                mins=(1 if z[0]=="+" else -1)*(int(z[1:3])*60+int(z[3:5]))
                d=d.replace(tzinfo=timezone(timedelta(minutes=mins)))
            else:d=d.replace(tzinfo=timezone.utc)
            return d.astimezone(timezone.utc)
        except (ValueError,TypeError):return None
    events=defaultdict(list)
    for p in programmes:
        name=" ".join(x.text or "" for x in p.findall("title"))
        pair=teams(name)
        start=xmltime(p.get("start"))
        end=xmltime(p.get("stop"))
        if pair and start and end and end>now and start<horizon and end>start:
            events[frozenset(pair)].append((start,end,"EPG",name))
    try:
        source=json.loads((ROOT/"reports"/"schedule-source-events.json").read_text(encoding="utf-8"))
        for items in source.get("sources",{}).values():
            for ev in items:
                pair=teams(ev.get("event",""))
                start=dated(ev.get("start_utc",""))
                if pair and start and now-timedelta(hours=4)<start<horizon:
                    events[frozenset(pair)].append((start,start+timedelta(hours=4),"iCal",ev["event"]))
    except (OSError,ValueError,TypeError,AttributeError):pass
    targets=defaultdict(list)
    for row in catalog:
        name=(row.get("ChannelName") or "").strip()
        target=(row.get("EPGID") or "").strip()
        if not target or target not in channels or not re.search(r"\b(?:NBA|NFL|NHL|MLB|MILB|MLS|WNBA|AHL|NCAAF|NCAAB)\s*(?:GAME\s*)?0*\d+\s*:",name,re.I):continue
        pair=teams(name.split(":",1)[-1])
        if pair:targets[target].append((name,pair))
    updates={}
    audit=[]
    for target,rows in targets.items():
        keys={frozenset(pair) for _,pair in rows}
        if len(keys)!=1:
            audit.append((target,"AMBIGUOUS_PROVIDER",""));continue
        key=next(iter(keys))
        options=events.get(key,[])
        # Only a single distinct scheduled start is sufficient evidence.
        starts=sorted({e[0] for e in options if e[1]>now})
        if len(starts)!=1:
            audit.append((target,"NO_UNIQUE_DATED_MATCH",str(len(starts))));continue
        start=starts[0]
        matching=[e for e in options if e[0]==start]
        end=min(e[1] for e in matching)
        if end<=start:continue
        label=start.astimezone(ET_ZONE).strftime("%B %d, %I:%M %p %Z")
        original=rows[0][1]
        # Retain the provider's team order when the source agrees.
        title=" @ ".join(x.strip() for x in re.split(r"\s+@\s+",rows[0][0].split(":",1)[-1],maxsplit=1)) if "@" in rows[0][0] else matching[0][3]
        title=title.strip()
        if not title:continue
        def programme(a,b,heading):
            p=ET.Element("programme",{"channel":target,"start":a.strftime("%Y%m%d%H%M%S +0000"),"stop":b.strftime("%Y%m%d%H%M%S +0000")})
            ET.SubElement(p,"title",{"lang":"en"}).text=heading
            ET.SubElement(p,"desc",{"lang":"en"}).text=title+" | "+label
            return p
        out=[]
        if now<start:out.append(programme(now,start,"Upcoming: "+title+" ("+label+")"))
        if end>now:out.append(programme(max(now,start),end,title+" ("+label+")"))
        if end<now+timedelta(days=2):out.append(programme(max(now,end),now+timedelta(days=2),"Event has Concluded"))
        updates[target]=out
        audit.append((target,"VERIFIED",matching[0][2]))
    if updates:
        programmes[:]=[p for p in programmes if p.get("channel") not in updates]
        for items in updates.values():programmes.extend(items)
    report=ROOT/"reports"/"original-name-calendar-matches.csv"
    report.parent.mkdir(exist_ok=True)
    with report.open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f);w.writerow(["EPGID","Status","Source"]);w.writerows(audit)
    print("Original-name dated EPG/iCal matches:",len(updates),"of",len(targets))

def apply(catalog,channels,programmes):
    by_stream={}
    for row in catalog:
        sid=str(row.get("StreamID") or "").strip()
        if not sid or not eligible(row):continue
        target=(row.get("EPGID") or "").strip() or "xtream."+sid
        if target in channels:by_stream[sid]=target
    now=datetime.now(timezone.utc)
    changed={}
    for item in load():
        sid=str(item.get("stream_id",""))
        target=by_stream.get(sid)
        if not target:continue
        try:
            start=datetime.fromisoformat(item["start_utc"]).astimezone(timezone.utc)
            duration=int(item["duration_hours"])
            if duration not in (4,12,24) or not -timedelta(days=6)<start-now<timedelta(days=9):continue
            sport=item["sport"]; event=item["event"]
            label=start.astimezone(ET_ZONE).strftime("%b %-d, %-I:%M %p %Z")
            name=event
            windows=[(now, start, "Next Game: "+event+" ("+label+")"),(start,start+timedelta(hours=duration),name),
                     (start+timedelta(hours=duration),now+timedelta(days=2),
                      'Event has Concluded')]
            output=[]
            for a,b,title in windows:
                a=max(a,now)
                b=min(b,now+timedelta(days=2))
                if b<=a:continue
                fmt=lambda d:d.strftime("%Y%m%d%H%M%S +0000")
                p=ET.Element("programme",{"channel":target,"start":fmt(a),"stop":fmt(b)})
                ET.SubElement(p,"title",{"lang":"en"}).text=title
                ET.SubElement(p,"desc",{"lang":"en"}).text=event+" | "+label
                output.append(p)
            if output:
                changed[target]=output
                if item.get("league")=="NCAAF":
                    ch=channels.get(target)
                    if ch is not None:
                        for display in ch.findall("display-name"):ch.remove(display)
                        number_match=next((re.search(r"NCAAF\s*0*(\d+)",row.get("ChannelName") or "",re.I) for row in catalog if str(row.get("StreamID") or "").strip()==sid),None)
                        ET.SubElement(ch,"display-name").text=("Game %02d" % int(number_match.group(1))) if number_match else "Game"
        except (KeyError,TypeError,ValueError):continue
    if changed:
        programmes[:]=[p for p in programmes if p.get("channel") not in changed]
        for output in changed.values():programmes.extend(output)
    print("AI sports EPG applied:",len(changed),"channels")
    match_original_names(catalog,channels,programmes)
if __name__=="__main__":research()
