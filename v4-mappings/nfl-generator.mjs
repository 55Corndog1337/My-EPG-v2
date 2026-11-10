// V4-only NFL XMLTV generator. Never reads or writes V2.
import fs from 'node:fs';
import path from 'node:path';

const TZ = 'America/New_York';
const esc = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const fmt = (ms,opts) => new Intl.DateTimeFormat('en-US',{timeZone:TZ,...opts}).format(new Date(ms));
const parts = ms => Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone:TZ,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(new Date(ms)).filter(x=>x.type!=='literal').map(x=>[x.type,x.value]));
const offset = ms => {const p=parts(ms);const wall=Date.UTC(+p.year,+p.month-1,+p.day,+p.hour,+p.minute,+p.second);return Math.round((wall-Math.floor(ms/1000)*1000)/60000)};
const stamp = ms => {const p=parts(ms);const o=offset(ms),sg=o>=0?'+':'-',abs=Math.abs(o);return `${p.year}${p.month}${p.day}${p.hour}${p.minute}${p.second} ${sg}${String(Math.floor(abs/60)).padStart(2,'0')}${String(abs%60).padStart(2,'0')}`};
const dateText = ms => fmt(ms,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'});
const dayText = ms => fmt(ms,{weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'});
const safeEvent = e => e && e.verified===true && typeof e.away==='string' && e.away.trim() && typeof e.home==='string' && e.home.trim() && Number.isFinite(Date.parse(e.kickoff)) && e.away!==e.home;
function eventFor(mapping,events){
 const relevant=events.filter(e=>safeEvent(e) && (e.source_channel_id===mapping.source_channel_id && mapping.source_channel_id || (mapping.channel.startsWith('NFL Teams - ') && Array.isArray(e.team_source_ids) && e.team_source_ids.includes(mapping.source_channel_id))));
 return relevant.sort((a,b)=>Date.parse(a.kickoff)-Date.parse(b.kickoff));
}
export function buildNFL(mappings,events,day='2026-11-09'){
 if(!/^\d{4}-\d{2}-\d{2}$/.test(day))throw Error('Expected YYYY-MM-DD');
 const start=localMidnight(day), next=new Date(day+'T12:00:00Z');next.setUTCDate(next.getUTCDate()+1);
 const end=localMidnight(next.toISOString().slice(0,10));
 const ids=new Set(),out=['<?xml version="1.0" encoding="UTF-8"?>','<tv generator-info-name="NFL V4 standalone">'];
 for(const m of mappings){
  const id='V4.NFL.'+m.xtream_stream_id;
  if(ids.has(id))throw Error('Duplicate StreamID: '+m.xtream_stream_id);
  ids.add(id);out.push(`<channel id="${esc(id)}"><display-name>${esc(m.channel)}</display-name></channel>`);
 }
 for(const m of mappings){
  const id='V4.NFL.'+m.xtream_stream_id;
  if(m.source==='static'){
   emit(out,id,start,end,m.programme_title||m.channel,m.programme_description||m.channel);continue;
  }
  const games=eventFor(m,events),bounds=new Set([start,end]);
  for(const e of games){const t=Date.parse(e.kickoff);if(t>start&&t<end)bounds.add(t);if(t+10800000>start&&t+10800000<end)bounds.add(t+10800000)}
  const sorted=[...bounds].sort((a,b)=>a-b);
  for(let i=0;i<sorted.length-1;i++){
   const a=sorted[i],b=sorted[i+1],current=games.find(e=>a>=Date.parse(e.kickoff)&&a<Date.parse(e.kickoff)+10800000);
   const upcoming=games.find(e=>Date.parse(e.kickoff)>a);
   const ended=games.filter(e=>Date.parse(e.kickoff)+10800000<=a).at(-1);
   let title='No Game Scheduled';
   if(current)title=`${current.away} @ ${current.home} (${dateText(Date.parse(current.kickoff))})`;
   else if(ended && (m.channel.startsWith('NFL Teams - ') || !upcoming))title='Event has Concluded';
   else if(upcoming)title=`Upcoming: ${upcoming.away} @ ${upcoming.home} (${dayText(Date.parse(upcoming.kickoff))})`;
   emit(out,id,a,b,title,title);
  }
 }
 out.push('</tv>');return out.join('\n')+'\n';
}
function emit(out,id,start,end,title,desc){if(end<=start)throw Error('Invalid programme interval');out.push(`<programme start="${stamp(start)}" stop="${stamp(end)}" channel="${esc(id)}"><title>${esc(title)}</title><desc>${esc(desc)}</desc></programme>`)}
function localMidnight(day){
 const target=Date.parse(day+'T00:00:00Z');let t=target;
 for(let i=0;i<4;i++)t=target-offset(t)*60000;
 if(parts(t).year+'-'+parts(t).month+'-'+parts(t).day!==day)throw Error('Bad local date');
 return t;
}
if(process.argv[1] && path.resolve(process.argv[1])===path.resolve(new URL(import.meta.url).pathname)){
 const dir=process.argv[2]||'v4-mappings',eventsFile=process.argv[3],day=process.argv[4]||new Date().toISOString().slice(0,10);
 if(!eventsFile)throw Error('Usage: node nfl-generator.mjs <mapping-dir> <verified-events.json> [YYYY-MM-DD]');
 const names=['nfl-games.json','nfl-teams.json','nfl-replay.json','nfl-special-channels.json'];
 const mappings=names.flatMap(n=>JSON.parse(fs.readFileSync(path.join(dir,n),'utf8')).mappings);
 const input=JSON.parse(fs.readFileSync(eventsFile,'utf8'));
 if(input.verified!==true || !Array.isArray(input.events))throw Error('Verified events snapshot required');
 process.stdout.write(buildNFL(mappings,input.events,day));
}
