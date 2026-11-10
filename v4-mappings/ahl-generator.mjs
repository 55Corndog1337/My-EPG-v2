#!/usr/bin/env node
// V4 AHL season guide generator. Requires the validated season CSV in this directory.
// Does not use EPG2, EPG6 or EPG37. Never modifies V2.
import fs from 'node:fs';
import path from 'node:path';
const dir=path.dirname(new URL(import.meta.url).pathname);
const csvPath=process.env.AHL_SEASON_CSV||path.join(dir,'ahl-season-2026-27.csv');
const outPath=process.env.AHL_XML_OUT||path.join(dir,'ahl.xml');
if(!fs.existsSync(csvPath))throw Error('Missing full-season AHL CSV: '+csvPath+'; refusing to generate incomplete guide');
function parseCsv(s){let rows=[],row=[],v='',quoted=false;for(let i=0;i<s.length;i++){let c=s[i];if(c==='"'){if(quoted&&s[i+1]==='"'){v+='"';i++}else quoted=!quoted}else if(c===','&&!quoted){row.push(v);v=''}else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&s[i+1]==='\n')i++;row.push(v);if(row.some(Boolean))rows.push(row);row=[];v=''}else v+=c}if(v||row.length){row.push(v);rows.push(row)}let h=rows.shift();return rows.map(r=>Object.fromEntries(h.map((k,i)=>[k,r[i]||''])));}
const esc=s=>String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const fmt=d=>{let x=new Date(d);return x.toISOString().replace(/[-:]/g,'').replace(/\.\d{3}Z$/,' +0000').replace('T','')};
const entries=parseCsv(fs.readFileSync(csvPath,'utf8').replace(/^\uFEFF/,''));
const required=['Season','StreamID','XMLTV_ID','Team','Away','Home','StartUTC','EndUTC'];
if(!entries.length||required.some(k=>!(k in entries[0])))throw Error('Invalid AHL season CSV schema');
const grouped=new Map();for(const r of entries){if(r.Season!=='2026-27'||!Number.isFinite(Date.parse(r.StartUTC))||!Number.isFinite(Date.parse(r.EndUTC)))throw Error('Invalid AHL season entry');if(new Date(r.EndUTC)-new Date(r.StartUTC)!==4*3600000)throw Error('AHL event must span four hours');if(!grouped.has(r.StreamID))grouped.set(r.StreamID,[]);grouped.get(r.StreamID).push(r)}
const lines=['<?xml version="1.0" encoding="UTF-8"?>','<tv generator-info-name="My-EPG V4 AHL">'];
for(const [id,rs] of grouped){lines.push('<channel id="'+esc(rs[0].XMLTV_ID)+'"><display-name>'+esc(rs[0].Team)+'</display-name></channel>')}
for(const [id,rs] of grouped){rs.sort((a,b)=>Date.parse(a.StartUTC)-Date.parse(b.StartUTC));for(let i=0;i<rs.length;i++){const r=rs[i];const start=Date.parse(r.StartUTC),end=Date.parse(r.EndUTC),next=rs[i+1]?Date.parse(rs[i+1].StartUTC):null;const title=esc(r.Title||r.Event||r.Away+' @ '+r.Home);const ch=esc(r.XMLTV_ID);lines.push('<programme channel="'+ch+'" start="'+fmt(r.StartUTC)+'" stop="'+fmt(r.EndUTC)+'"><title>'+title+'</title><desc>'+esc(r.Event||r.Away+' @ '+r.Home)+'</desc></programme>');if(next!==null&&next>end){lines.push('<programme channel="'+ch+'" start="'+fmt(new Date(end).toISOString())+'" stop="'+fmt(new Date(next).toISOString())+'"><title>Upcoming: '+esc(rs[i+1].Event||rs[i+1].Away+' @ '+rs[i+1].Home)+'</title></programme>')}}}
lines.push('</tv>');fs.writeFileSync(outPath,lines.join('\n')+'\n');console.log(JSON.stringify({output:outPath,channels:grouped.size,events:entries.length}));
