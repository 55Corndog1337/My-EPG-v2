import csv, gzip, io, os, re, threading, queue, urllib.request, urllib.parse, urllib.error, json, xml.etree.ElementTree as ET, shutil, copy, webbrowser, tempfile, base64, hashlib, difflib
from datetime import datetime, timezone, timedelta
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from collections import defaultdict, Counter
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote

SPORT = re.compile(r'\b(NBA|NFL|MLB|NHL|AHL|MLS|WNBA|NCAA|FLOSPORTS|ESPN\+?)\b', re.I)
NUM = re.compile(r'\b(?:GAME|FEED|CHANNEL|CH|EVENT)?\s*0*(\d{1,3})\b', re.I)
IDNUM = re.compile(r'^(\d+)(\.[A-Za-z][\w-]*)$')
COUNTRIES = {'US':'USA','USA':'USA','UNITED STATES':'USA','CA':'Canada','CAN':'Canada','CANADA':'Canada','UK':'UK','GB':'UK','UNITED KINGDOM':'UK','AU':'Australia','AUS':'Australia','DE':'Germany','GERMANY':'Germany','FR':'France','FRANCE':'France','IN':'India','INDIA':'India'}

def country(s):
    s = (s or '').upper()
    for token in re.split(r'[^A-Z]+', s):
        if token in COUNTRIES: return COUNTRIES[token]
    return 'Unspecified'

def league_number(s):
    s=(s or '').upper().replace('_',' ').replace('-',' ')
    m=SPORT.search(s)
    if not m:return None
    tail=s[m.end():]
    n=NUM.search(tail)
    return (m.group(1), int(n.group(1))) if n else None

def norm(s):return re.sub(r'[^A-Z0-9]+','',s.upper())

def open_source(path):
    if path.startswith(('https://','http://')):
        req=urllib.request.Request(path,headers={'User-Agent':'IPTV-EPG-ID-Matcher/1.0'})
        response=urllib.request.urlopen(req,timeout=45)
        raw=response.read()
        if raw[:2]==b'\x1f\x8b':raw=gzip.decompress(raw)
        return io.BytesIO(raw)
    if path.lower().endswith('.gz'):return gzip.open(path,'rb')
    return open(path,'rb')

def stream_channel_id(url):
    """Best-effort stream ID, which is distinct from an XMLTV ID."""
    try:
        parts=urlsplit(url)
        query=parse_qs(parts.query)
        for key in ('stream_id','channel_id','channel','id'):
            if query.get(key):return query[key][0]
        segments=[unquote(x) for x in parts.path.split('/') if x]
        if segments:
            match=re.fullmatch(r'(\d+)(?:\.(?:ts|m3u8|mp4|mkv))?',segments[-1],re.I)
            if match:return match.group(1)
    except (ValueError,TypeError):pass
    return ''

def channel_id_record(c,linked=''):
    return [c['name'],c['country'],c['group'],c.get('stream_id',''),c['id'],linked]

def safe_csv(value):
    value=str(value or '')
    return "'"+value if value.startswith(('=','+','-','@')) else value

def parse_m3u(path):
    with open_source(path) as f: data=f.read().decode('utf-8-sig','replace')
    result=[]; meta=None
    for line in data.splitlines():
        line=line.strip()
        if line.startswith('#EXTINF:'):
            attrs=dict(re.findall(r'([\w-]+)\s*=\s*"([^"]*)"',line))
            name=line.rsplit(',',1)[-1].strip()
            meta={'name':name,'id':attrs.get('tvg-id',''),'group':attrs.get('group-title',''),'country':country(' '.join([name,attrs.get('group-title',''),attrs.get('tvg-country','')])), 'url':'','stream_id':'','source':Path(path).name,'logo':attrs.get('tvg-logo','')}
        elif meta and line and not line.startswith('#'):
            meta['url']=line;meta['stream_id']=stream_channel_id(line);result.append(meta);meta=None
    return result

def xtream_api(server, username, password, action=None, **params):
    """Read Xtream player_api.php; credentials are only held in memory."""
    server=server.strip().rstrip('/')
    if not server.startswith(('http://','https://')):
        raise ValueError('Enter a complete http:// or https:// server URL, including port if required.')
    parsed=urlsplit(server)
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Enter the server URL without embedded credentials.')
    query={'username':username,'password':password}
    if action:query['action']=action
    query.update(params)
    url=server+'/player_api.php?'+urllib.parse.urlencode(query)
    request=urllib.request.Request(url,headers={'User-Agent':'IPTV-EPG-ID-Matcher/2.0','Accept':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=35) as resp:
            data=resp.read(32*1024*1024)
    except Exception as ex:
        raise RuntimeError('Xtream server request failed. Check server, credentials, and connection. ('+type(ex).__name__+')') from None
    try:return json.loads(data.decode('utf-8-sig'))
    except (UnicodeDecodeError,json.JSONDecodeError):raise ValueError('Server did not return valid Xtream JSON. Check the server address.') from None

def xtream_channels(server,username,password,categories):
    """Retrieve selected live categories; do not alter server or original playlists."""
    rows=[]
    for category in categories:
        cid=str(category.get('category_id',''))
        data=xtream_api(server,username,password,'get_live_streams',category_id=cid)
        if not isinstance(data,list):raise ValueError('Invalid channel list for category '+str(category.get('category_name','')))
        for entry in data:
            sid=str(entry.get('stream_id',''))
            if not sid:continue
            group=str(category.get('category_name') or '(Ungrouped)')
            name=str(entry.get('name') or 'Channel '+sid)
            ext=str(entry.get('container_extension') or 'ts')
            if ext not in ('ts','m3u8'):ext='ts'
            url=server.rstrip('/')+'/live/'+urllib.parse.quote(username,safe='')+'/'+urllib.parse.quote(password,safe='')+'/'+urllib.parse.quote(sid,safe='')+'.'+ext
            rows.append({'name':name,'id':str(entry.get('epg_channel_id') or ''),'group':group,'country':country(name+' '+group),'url':url,'stream_id':sid,'source':'Xtream Codes','category_id':cid,'logo':str(entry.get('stream_icon') or '')})
    return rows

def xmltv_local_time(value):
    if not value:return ''
    try:
        value=value.strip()
        dt=datetime.strptime(value[:14],'%Y%m%d%H%M%S')
        offset=value[14:].strip()
        if offset and re.fullmatch(r'[+-]\d{4}',offset):
            dt=datetime.strptime(value[:14]+' '+offset,'%Y%m%d%H%M%S %z').astimezone()
        return dt.strftime('%a %b %d, %I:%M %p').replace(' 0', ' ')
    except (ValueError,TypeError):return value

def parse_epg(path):
    channels={}; counts=defaultdict(int); samples=defaultdict(list); listings=defaultdict(list)
    with open_source(path) as f:
        for event,elem in ET.iterparse(f,events=('end',)):
            if elem.tag=='channel':
                cid=elem.get('id','');names=[x.text or '' for x in elem.findall('display-name')]
                if cid:channels[cid]={'id':cid,'name':next((n for n in names if n),cid),'aliases':names,'country':country(' '.join(names+[cid])),'source':Path(path).name,'logo':(elem.find('icon').get('src','') if elem.find('icon') is not None else '')}
                elem.clear()
            elif elem.tag=='programme':
                cid=elem.get('channel','');counts[cid]+=1
                if len(listings[cid])<60:
                    title=elem.findtext('title') or '(Untitled)'
                    desc=elem.findtext('desc') or ''
                    subtitle=elem.findtext('sub-title') or ''
                    listings[cid].append((elem.get('start',''),elem.get('stop',''),title,subtitle,desc))
                    if len(samples[cid])<3:samples[cid].append(title)
                elem.clear()
    for cid,ch in channels.items():ch['count']=counts[cid];ch['sample']=' | '.join(samples[cid]);ch['listings']=sorted(listings[cid],key=lambda x:x[0])
    return list(channels.values())

class Matcher:
 def __init__(self,root):
    self.root=root;root.title('IPTV EPG Manager 2.3 — Batch Smart Match');root.geometry('1420x830')
    self.enabled_groups=None;self.playlist=[];self.epgs=[];self.links={};self.link_sources={};self.filtered=[];self.q=queue.Queue();self.undo=[];self.epg_paths={};self.playlist_path='';self.project_path='';self.xtream_session=None;self.auto_refresh=tk.BooleanVar(value=False);self.refresh_minutes=tk.IntVar(value=180);self._last_refresh=datetime.now(timezone.utc)
    top=ttk.Frame(root,padding=8);top.pack(fill='x')
    for label,cmd in [('Load M3U',self.load_m3u),('Connect Xtream',self.connect_xtream),('Add XMLTV / XML.GZ',self.load_epg),('Add EPG URL',self.load_epg_url),('Load Matches CSV',self.load_links),('Save Matches CSV',self.save_links),('Export Linked M3U',self.export_m3u),('Clear All',self.clear)]:ttk.Button(top,text=label,command=cmd).pack(side='left',padx=3)
    flt=ttk.Frame(root,padding=8);flt.pack(fill='x')
    ttk.Label(flt,text='Country:').pack(side='left');self.ct=tk.StringVar(value='All');self.cb=ttk.Combobox(flt,textvariable=self.ct,values=['All','USA','Canada','UK','Australia','Germany','France','India','Unspecified'],width=15,state='readonly');self.cb.pack(side='left',padx=5);self.cb.bind('<<ComboboxSelected>>',lambda e:self.refresh())
    ttk.Button(flt,text='Choose Categories...',command=self.choose_categories).pack(side='left',padx=3)
    ttk.Label(flt,text='Category:').pack(side='left');self.group_filter=tk.StringVar(value='All');self.group_cb=ttk.Combobox(flt,textvariable=self.group_filter,values=['All'],width=21,state='readonly');self.group_cb.pack(side='left',padx=5);self.group_cb.bind('<<ComboboxSelected>>',lambda e:self.refresh())
    ttk.Label(flt,text='Search:').pack(side='left');self.search=tk.StringVar();ttk.Entry(flt,textvariable=self.search,width=32).pack(side='left',padx=5);self.search.trace_add('write',lambda *_:self.refresh())
    ttk.Label(flt,text='Status:').pack(side='left');self.status_filter=tk.StringVar(value='All');self.scb=ttk.Combobox(flt,textvariable=self.status_filter,values=['All','Unmatched (no usable EPG)','Unlinked (not approved)','Linked / has listings','Linked / missing EPG','Ambiguous EPG'],width=12,state='readonly');self.scb.pack(side='left',padx=5);self.scb.bind('<<ComboboxSelected>>',lambda e:self.refresh())
    ttk.Label(flt,text='EPG Source:').pack(side='left');self.source_filter=tk.StringVar(value='All');self.source_cb=ttk.Combobox(flt,textvariable=self.source_filter,values=['All'],width=20,state='readonly');self.source_cb.pack(side='left',padx=5);self.source_cb.bind('<<ComboboxSelected>>',lambda e:self.refresh())
    ttk.Button(flt,text='Next Unmatched',command=self.next_unmatched).pack(side='left',padx=3)
    ttk.Button(flt,text='Export Unmatched',command=self.export_unmatched).pack(side='left',padx=3)
    ttk.Button(flt,text='Suggest Match',command=self.suggest).pack(side='left',padx=5)
    self.stats=ttk.Label(flt,text='Load a playlist and one or more EPG files');self.stats.pack(side='right')
    panes=ttk.Panedwindow(root,orient='horizontal');panes.pack(fill='both',expand=True,padx=8,pady=5)
    left=ttk.Frame(panes);right=ttk.Frame(panes);panes.add(left,weight=3);panes.add(right,weight=3)
    ttk.Label(left,text='PLAYLIST CHANNELS (select a channel)',font=('Segoe UI',11,'bold')).pack(anchor='w')
    self.pt=ttk.Treeview(left,columns=('position','status','name','game','country','group','streamid','playlistid','epgid','epgsource'),show='headings',selectmode='extended')
    for key,title,w in [('position','#',65),('status','Match Status',155),('name','Channel Name',220),('game','Game #',70),('country','Country',75),('group','Group',110),('streamid','Stream ID',100),('playlistid','Playlist tvg-id',135),('epgid','Linked XMLTV ID',155),('epgsource','EPG Source',165)]:self.pt.heading(key,text=title);self.pt.column(key,width=w,stretch=key in ('name','group'))
    self.pt.tag_configure('missing',background='#ffe0df',foreground='#7c1515')
    self.pt.tag_configure('unlinked',background='#fff1cc',foreground='#604500')
    self.pt.tag_configure('working',background='#dff3e5',foreground='#174f2a')
    self.pt.tag_configure('ambiguous',background='#f1e5ff',foreground='#4c2373')
    self.pt.pack(fill='both',expand=True);self.pt.bind('<<TreeviewSelect>>',lambda e:self.selection_changed())
    ttk.Label(right,text='EPG CHANNELS (select matching ID)',font=('Segoe UI',11,'bold')).pack(anchor='w')
    self.et=ttk.Treeview(right,columns=('id','name','country','count','source'),show='headings',selectmode='browse')
    for key,title,w in [('id','XMLTV ID',150),('name','EPG Name',230),('country','Country',80),('count','Programmes',80),('source','Source',140)]:self.et.heading(key,text=title);self.et.column(key,width=w,stretch=key=='name')
    self.et.pack(fill='both',expand=True)
    bottom=ttk.Frame(root,padding=8);bottom.pack(fill='x')
    ttk.Button(bottom,text='Batch Smart Match Selected',command=self.batch_smart_match).pack(side='left',padx=3)
    ttk.Button(bottom,text='Select Visible',command=self.select_visible).pack(side='left',padx=3)
    ttk.Button(bottom,text='Link Selected',command=self.link).pack(side='left',padx=3)
    ttk.Button(bottom,text='Preview EPG',command=self.preview_epg).pack(side='left',padx=3)
    ttk.Button(bottom,text='Preview Category Guide',command=self.preview_category).pack(side='left',padx=3)
    ttk.Button(bottom,text='Copy Channel IDs',command=self.copy_ids).pack(side='left',padx=3)
    ttk.Button(bottom,text='Export Channel ID Audit',command=self.export_ids).pack(side='left',padx=3)
    ttk.Button(bottom,text='Unlink',command=self.unlink).pack(side='left',padx=3)
    ttk.Button(bottom,text='Preview Sequential Bulk Link',command=self.bulk_preview).pack(side='left',padx=3)
    ttk.Button(bottom,text='Undo Last Bulk Link',command=self.undo_bulk).pack(side='left',padx=3)
    extras=ttk.Frame(root,padding=5);extras.pack(fill='x')
    for n,(label,cmd) in enumerate([('Smart Match Review',self.smart_match),('Save Project',self.save_project),('Open Project',self.open_project),('Coverage 24/48/72h',self.coverage_report),('Compare EPGs',self.compare_epgs),('Generate XMLTV.GZ',self.generate_guide),('Export TiviMate Pair M3U',self.export_tivimate_pair),('Refresh Guides',self.refresh_guides),('Backup Mappings',self.backup_mappings),('Restore Backup',self.restore_backup),('Xtream EPG Compare',self.xtream_epg_compare),('Logos / Artwork',self.show_logos),('Export to My-EPG-v2',self.export_github_matches),('GitHub Sync / Dashboard',self.github_dashboard),('Detect Channel Changes',self.detect_changes),('Sports Assistant',self.sports_assistant)]):ttk.Button(extras,text=label,command=cmd).grid(row=n//7,column=n%7,sticky='w',padx=2,pady=2)
    ttk.Checkbutton(extras,text='Auto-refresh (every 3h while open)',variable=self.auto_refresh).grid(row=2,column=0,columnspan=3,sticky='w',padx=3)
    self.details=tk.StringVar(value='Select a playlist channel to see its stream URL, existing ID and EPG candidates.');ttk.Label(root,textvariable=self.details,wraplength=1360,padding=8).pack(fill='x')
    self.root.after(150,self.poll)
 def work(self,fn,callback):
    def run():
        try:self.q.put(('ok',callback,fn()))
        except Exception as ex:self.q.put(('error',None,str(ex)))
    threading.Thread(target=run,daemon=True).start()
 def poll(self):
    try:
        while True:
            typ,cb,val=self.q.get_nowait()
            if typ=='ok':cb(val)
            else:messagebox.showerror('Import error',val)
    except queue.Empty:pass
    self.root.after(150,self.poll)
    if self.auto_refresh.get() and (datetime.now(timezone.utc)-self._last_refresh).total_seconds()>max(15,self.refresh_minutes.get())*60:self.refresh_guides()
 def connect_xtream(self):
    win=tk.Toplevel(self.root);win.title('Connect to Xtream Codes — Live TV');win.geometry('540x330');win.transient(self.root)
    frame=ttk.Frame(win,padding=15);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='Xtream Codes server connection',font=('Segoe UI',13,'bold')).pack(anchor='w',pady=(0,8))
    values={}
    for label,key,secret in [('Server URL (with port)','server',False),('Username','username',False),('Password','password',True)]:
        ttk.Label(frame,text=label).pack(anchor='w')
        var=tk.StringVar();values[key]=var
        ttk.Entry(frame,textvariable=var,show='*' if secret else '',width=58).pack(fill='x',pady=(0,7))
    status=ttk.Label(frame,text='Credentials are not saved. Only Live TV categories are retrieved.',wraplength=490);status.pack(anchor='w',pady=7)
    def connect():
        server=values['server'].get().strip().rstrip('/')
        user=values['username'].get();password=values['password'].get()
        if not (server and user and password):messagebox.showwarning('Missing details','Enter server URL, username, and password.',parent=win);return
        status.config(text='Connecting and retrieving Live TV categories...')
        def fetch():
            auth=xtream_api(server,user,password)
            if not isinstance(auth,dict) or str((auth.get('user_info') or {}).get('auth','')) not in ('1','True','true'):
                raise ValueError('Xtream login was not authorized by the server.')
            categories=xtream_api(server,user,password,'get_live_categories')
            if not isinstance(categories,list):raise ValueError('Server returned no valid Live TV category list.')
            return server,user,password,categories,auth.get('user_info',{})
        def loaded(result):
            if win.winfo_exists():win.destroy()
            self.xtream_choose_categories(*result)
        self.work(fetch,loaded)
    ttk.Button(frame,text='Connect & Choose Categories',command=connect).pack(anchor='e',pady=7)
 def xtream_choose_categories(self,server,user,password,categories,user_info):
    win=tk.Toplevel(self.root);win.title('Select Xtream Live TV Categories');win.geometry('540x610');win.transient(self.root)
    ttk.Label(win,text=f"Select categories to import ({len(categories):,} available)",font=('Segoe UI',12,'bold'),padding=10).pack(anchor='w')
    ttk.Label(win,text='Only checked categories will be downloaded. Existing playlist data is replaced after import.',padding=(10,0)).pack(anchor='w')
    holder=ttk.Frame(win);holder.pack(fill='both',expand=True,padx=10,pady=8)
    canvas=tk.Canvas(holder,highlightthickness=0);scroll=ttk.Scrollbar(holder,orient='vertical',command=canvas.yview)
    inner=ttk.Frame(canvas);inner.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.create_window((0,0),window=inner,anchor='nw');canvas.configure(yscrollcommand=scroll.set)
    canvas.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
    choices=[]
    for c in categories:
        var=tk.BooleanVar(value=False);choices.append((c,var))
        ttk.Checkbutton(inner,text=str(c.get('category_name') or c.get('category_id')),variable=var).pack(anchor='w',pady=2)
    bar=ttk.Frame(win,padding=10);bar.pack(fill='x')
    ttk.Button(bar,text='Select All',command=lambda:[v.set(True) for _,v in choices]).pack(side='left',padx=3)
    ttk.Button(bar,text='Select None',command=lambda:[v.set(False) for _,v in choices]).pack(side='left',padx=3)
    def load():
        selected=[c for c,v in choices if v.get()]
        if not selected:messagebox.showwarning('No categories','Check at least one category.',parent=win);return
        win.destroy()
        def fetch():return xtream_channels(server,user,password,selected)
        def loaded(rows):
            self.set_m3u(rows);self.xtream_session=(server,user,password)
            messagebox.showinfo('Xtream import',f'Loaded {len(rows):,} live channels from {len(selected)} selected categories. Stream IDs and provider EPG IDs are available in the main table.')
        self.work(fetch,loaded)
    ttk.Button(bar,text='Import Selected Categories',command=load).pack(side='right',padx=3)
 def choose_categories(self):
    if not self.playlist:
        messagebox.showinfo('Categories','Import your playlist first.');return
    groups=sorted({ch['group'] or '(Ungrouped)' for ch in self.playlist},key=str.casefold)
    win=tk.Toplevel(self.root);win.title('Choose IPTV Categories');win.geometry('470x570');win.transient(self.root)
    ttk.Label(win,text='Check categories to include in the matcher:',padding=8).pack(anchor='w')
    outer=ttk.Frame(win);outer.pack(fill='both',expand=True,padx=10)
    canvas=tk.Canvas(outer,highlightthickness=0);scroll=ttk.Scrollbar(outer,orient='vertical',command=canvas.yview)
    inner=ttk.Frame(canvas);inner.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.create_window((0,0),window=inner,anchor='nw');canvas.configure(yscrollcommand=scroll.set)
    canvas.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
    selected={g:tk.BooleanVar(value=(self.enabled_groups is None or g in self.enabled_groups)) for g in groups}
    for g in groups:
        n=sum((ch['group'] or '(Ungrouped)')==g for ch in self.playlist)
        ttk.Checkbutton(inner,text=f'{g} ({n:,})',variable=selected[g]).pack(anchor='w',pady=2)
    actions=ttk.Frame(win,padding=8);actions.pack(fill='x')
    ttk.Button(actions,text='Select All',command=lambda:[v.set(True) for v in selected.values()]).pack(side='left',padx=3)
    ttk.Button(actions,text='Select None',command=lambda:[v.set(False) for v in selected.values()]).pack(side='left',padx=3)
    def apply():
        self.enabled_groups={g for g,v in selected.items() if v.get()}
        if len(self.enabled_groups)==len(groups):self.enabled_groups=None
        if self.group_filter.get()!='All' and self.group_filter.get() not in (self.enabled_groups or groups):self.group_filter.set('All')
        self.refresh();win.destroy()
    ttk.Button(actions,text='Apply Selection',command=apply).pack(side='right',padx=3)
    ttk.Button(actions,text='Cancel',command=win.destroy).pack(side='right',padx=3)
 def load_m3u(self):
    p=filedialog.askopenfilename(filetypes=[('M3U Playlist','*.m3u *.m3u8'),('All','*.*')]);
    if p:self.work(lambda:parse_m3u(p),lambda rows:(self.set_m3u(rows),setattr(self,'playlist_path',p)))
 def set_m3u(self,rows):self.enabled_groups=None;self.playlist=rows;self.links={};self.link_sources={};self.group_cb['values']=['All']+sorted({x['group'] or '(Ungrouped)' for x in rows});self.group_filter.set('All');self.refresh();messagebox.showinfo('Loaded',f'{len(rows):,} playlist channels imported.')
 def load_epg(self):
    p=filedialog.askopenfilename(filetypes=[('XMLTV','*.xml *.gz'),('All','*.*')]);
    if p:self.work(lambda:parse_epg(p),lambda rows:(self.add_epg(rows),self.epg_paths.update({Path(p).name:p})))
 def load_epg_url(self):
    from tkinter import simpledialog
    url=simpledialog.askstring('Add XMLTV URL','Enter direct XMLTV or XML.GZ URL (HTTP/HTTPS):',parent=self.root)
    if not url:return
    if not url.startswith(('http://','https://')):messagebox.showerror('Invalid URL','Use http:// or https://');return
    # Give each URL a stable, non-sensitive source label.
    import hashlib
    name='URL_'+hashlib.sha256(url.encode()).hexdigest()[:10]+'.xml.gz'
    def fetch():
        # URL may omit .gz; gzip content is auto-detected by open_source.
        rows=parse_epg(url)
        for row in rows:row['source']=name
        return rows
    self.work(fetch,lambda rows:(self.add_epg(rows),self.epg_paths.update({name:url})))
 def add_epg(self,rows):
    existing={(x['source'],x['id']) for x in self.epgs};self.epgs.extend(x for x in rows if (x['source'],x['id']) not in existing);self.source_cb['values']=['All']+sorted({x['source'] for x in self.epgs});self.refresh();messagebox.showinfo('Loaded',f'{len(rows):,} XMLTV channels imported. Total {len(self.epgs):,}.')
 def clear(self):
    if messagebox.askyesno('Clear','Clear imported data and all links?'):self.enabled_groups=None;self.playlist=[];self.epgs=[];self.links={};self.link_sources={};self.epg_paths={};self.playlist_path='';self.xtream_session=None;self.source_filter.set('All');self.source_cb['values']=['All'];self.group_filter.set('All');self.group_cb['values']=['All'];self.refresh()
 def epg_status(self,i,lookup=None):
    """Status distinguishes explicit approvals from mere matching tvg-id metadata."""
    ch=self.playlist[i]
    if lookup is None:
        lookup=defaultdict(list)
        for e in self.epgs:lookup[e['id']].append(e)
    if i in self.links:
        options=[e for e in lookup.get(self.links[i],[]) if e['source']==self.link_sources.get(i)]
        return ('Linked / has listings','working') if any(e['count'] for e in options) else ('Linked / missing EPG','missing')
    matches=lookup.get(ch['id'],[]) if ch['id'] else []
    if len(matches)>1:return ('Ambiguous EPG','ambiguous')
    if len(matches)==1 and matches[0]['count']>0:return ('Unlinked (ID found)','unlinked')
    return ('Unmatched (no EPG)','missing')
 def refresh(self):
    psel=self.pt.selection();old=[int(x) for x in psel]
    self.pt.delete(*self.pt.get_children());q=self.search.get().lower();ct=self.ct.get();status=self.status_filter.get();self.filtered=[]
    lookup=defaultdict(list)
    for e in self.epgs:lookup[e['id']].append(e)
    counts=defaultdict(int)
    for i,ch in enumerate(self.playlist):
        label,tag=self.epg_status(i,lookup);counts[tag]+=1
        linked=self.links.get(i,'')
        if self.enabled_groups is not None and (ch['group'] or '(Ungrouped)') not in self.enabled_groups:continue
        if ct!='All' and ch['country']!=ct:continue
        if self.group_filter.get()!='All' and (ch['group'] or '(Ungrouped)')!=self.group_filter.get():continue
        if q and q not in (ch['name']+' '+ch['group']+' '+ch['id']+' '+ch.get('stream_id','')+' '+linked+' '+str(i+1)).lower():continue
        if status=='Unmatched (no usable EPG)' and label!='Unmatched (no EPG)':continue
        if status=='Unlinked (not approved)' and not label.startswith('Unlinked'):continue
        if status=='Linked / has listings' and label!='Linked / has listings':continue
        if status=='Linked / missing EPG' and label!='Linked / missing EPG':continue
        if status=='Ambiguous EPG' and label!='Ambiguous EPG':continue
        self.filtered.append(i)
        self.pt.insert('','end',iid=str(i),values=(i+1,label,ch['name'],(league_number(ch['name']) or ('',''))[1],ch['country'],ch['group'],ch.get('stream_id',''),ch['id'],linked,self.link_sources.get(i,'')),tags=(tag,))
    self.stats.config(text=f"Showing {len(self.filtered):,}/{len(self.playlist):,} | Unmatched {counts['missing']:,} | Needs approval {counts['unlinked']:,} | Ambiguous {counts['ambiguous']:,} | Working {counts['working']:,}")
    restored=[str(i) for i in old if i in self.filtered]
    if restored:self.pt.selection_set(restored)
    if self.selected_p() is not None:self.update_epg()
    else:self.et.delete(*self.et.get_children())
 def next_unmatched(self):
    self.status_filter.set('Unmatched (no usable EPG)');self.refresh()
    rows=self.pt.get_children()
    if not rows:
        messagebox.showinfo('Unmatched','No unmatched channels under the current country, category, and search filters.');return
    selected=self.pt.selection();start=rows.index(selected[0])+1 if selected and selected[0] in rows else 0
    iid=rows[start%len(rows)];self.pt.selection_set(iid);self.pt.focus(iid);self.pt.see(iid);self.selection_changed()
 def export_unmatched(self):
    if not self.playlist:return
    path=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV','*.csv')],initialfile='unmatched_channels.csv')
    if not path:return
    lookup=defaultdict(list)
    for e in self.epgs:lookup[e['id']].append(e)
    n=0
    with open(path,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['playlist_number','status','channel_name','country','category','stream_id','playlist_tvg_id','linked_xmltv_id','epg_source'])
        for i,c in enumerate(self.playlist):
            label,_=self.epg_status(i,lookup)
            if label not in ('Unmatched (no EPG)','Linked / missing EPG','Ambiguous EPG'):continue
            w.writerow([i+1,label,c['name'],c['country'],c['group'],c.get('stream_id',''),c['id'],self.links.get(i,''),self.link_sources.get(i,'')]);n+=1
    messagebox.showinfo('Exported',f'{n:,} unmatched, broken, or ambiguous channels exported without stream URLs.')
 def update_epg(self):
    self.et.delete(*self.et.get_children());q=self.search.get().lower();ct=self.ct.get();source=self.source_filter.get();selected=self.selected_p();p=self.playlist[selected] if selected is not None else None
    candidates=[]
    for i,ch in enumerate(self.epgs):
        if source!='All' and ch['source']!=source:continue
        if ct!='All' and ch['country'] not in (ct,'Unspecified'):continue
        score=self.score(p,ch) if p else 0
        if q and q not in (ch['id']+' '+ch['name']).lower() and score<70:continue
        candidates.append((score,i,ch))
    candidates.sort(key=lambda x:(-x[0],x[2]['name']))
    for _,i,ch in candidates[:3000]:self.et.insert('','end',iid=str(i),values=(ch['id'],ch['name'],ch['country'],ch['count'],ch['source']))
 def score(self,p,e):
    if not p:return 0
    if p['id'] and p['id']==e['id']:return 100
    if norm(p['name'])==norm(e['name']):return 95
    pn=league_number(p['name']);en=league_number(e['name'])
    if pn and en and pn==en:
        if p['country']!=e['country'] and p['country']!='Unspecified' and e['country']!='Unspecified':return 0
        return 85
    if pn and en and pn!=en:return 0
    if pn or en:return 0
    if norm(p['name']) in norm(e['name']) or norm(e['name']) in norm(p['name']):return 50
    return 0
 def selected_p(self):
    sel=self.pt.selection();return int(sel[0]) if sel else None
 def selected_e(self):
    sel=self.et.selection();return int(sel[0]) if sel else None
 def selection_changed(self):
    i=self.selected_p()
    if i is None:return
    p=self.playlist[i];self.details.set(f"Playlist #{i+1} | Channel: {p['name']} | Country: {p['country']} | Stream channel ID: {p.get('stream_id') or '(not detectable)'} | Original tvg-id: {p['id'] or '(blank)'} | Linked: {self.links.get(i,'(none)')}")
    self.update_epg()
 def suggest(self):
    i=self.selected_p()
    if i is None:return
    p=self.playlist[i];scored=sorted(((self.score(p,e),j) for j,e in enumerate(self.epgs) if self.source_filter.get()=='All' or e['source']==self.source_filter.get()),reverse=True)
    if not scored or scored[0][0]<70:messagebox.showinfo('No safe suggestion','No strong match found. Choose an EPG channel manually.');return
    score,j=scored[0]
    if len(scored)>1 and scored[1][0]==score:messagebox.showwarning('Ambiguous',f'Multiple EPG IDs scored {score}. Please select one manually.');return
    if str(j) in self.et.get_children():self.et.selection_set(str(j));self.et.see(str(j))
    messagebox.showinfo('Suggestion',f"Suggested: {self.epgs[j]['id']} ({self.epgs[j]['name']})\nScore: {score}. Click Link Selected to approve.")
 def preview_epg(self, channel_index=None, epg_entry=None):
    i=self.selected_p() if channel_index is None else channel_index
    j=self.selected_e() if epg_entry is None else None
    e=epg_entry if epg_entry is not None else (self.epgs[j] if j is not None else None)
    if e is None and i is not None:
        cid=self.links.get(i);source=self.link_sources.get(i)
        e=next((x for x in self.epgs if x['id']==cid and x['source']==source),None)
    if e is None:
        messagebox.showinfo('Preview EPG','Select an EPG channel on the right, or select a playlist channel with an approved EPG link.')
        return
    win=tk.Toplevel(self.root);win.title('EPG Preview — '+e['name']+' — '+e['source']);win.geometry('1040x620')
    header=ttk.Frame(win,padding=12);header.pack(fill='x')
    title=(self.playlist[i]['name']+'  →  ' if i is not None else '')+e['name']
    ttk.Label(header,text=title,font=('Segoe UI',15,'bold'),wraplength=980).pack(anchor='w')
    ttk.Label(header,text=f"XMLTV ID: {e['id']}     Source: {e['source']}     Total programmes: {e['count']:,}").pack(anchor='w',pady=5)
    ttk.Label(header,text='Showing up to 60 imported programmes. Times are converted to your computer’s local timezone when the XMLTV provides an offset. This previews guide metadata, not video playback.',wraplength=980).pack(anchor='w')
    cols=('start','end','title','subtitle');tree=ttk.Treeview(win,columns=cols,show='headings',selectmode='browse')
    for col,label,width in [('start','Starts',170),('end','Ends',170),('title','Programme title',420),('subtitle','Episode / subtitle',240)]:
        tree.heading(col,text=label);tree.column(col,width=width,stretch=col in ('title','subtitle'))
    frame=ttk.Frame(win,padding=(12,4,12,0));frame.pack(fill='both',expand=True)
    scroll=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);tree.configure(yscrollcommand=scroll.set)
    tree.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
    entries=e.get('listings',[])
    for idx,(start,stop,name,sub,desc) in enumerate(entries):tree.insert('','end',iid=str(idx),values=(xmltv_local_time(start),xmltv_local_time(stop),name,sub))
    descbox=tk.Text(win,height=7,wrap='word',font=('Segoe UI',10));descbox.pack(fill='x',padx=12,pady=(5,12))
    def show_description(_=None):
        sel=tree.selection()
        if not sel:return
        start,stop,name,sub,desc=entries[int(sel[0])]
        descbox.config(state='normal');descbox.delete('1.0','end');descbox.insert('1.0',f'{name}\n{desc or "No programme description supplied by this EPG."}');descbox.config(state='disabled')
    tree.bind('<<TreeviewSelect>>',show_description)
    if entries:tree.selection_set('0');show_description()
    else:
        descbox.insert('1.0','No programme entries found for this channel in the imported EPG.');descbox.config(state='disabled')

 def preview_category(self):
    """Browse the actual XMLTV schedule across every IPTV channel in one category."""
    selected=self.selected_p()
    group=self.group_filter.get()
    if group=='All' and selected is not None:group=self.playlist[selected]['group'] or '(Ungrouped)'
    if group=='All':
        messagebox.showinfo('Select category','Choose a category in the Category filter, or select a playlist channel first.');return
    ct=self.ct.get();source_filter=self.source_filter.get()
    indices=[i for i,c in enumerate(self.playlist) if (c['group'] or '(Ungrouped)')==group and (ct=='All' or c['country']==ct)]
    if not indices:
        messagebox.showinfo('Empty category','No playlist channels in this category with the selected country filter.');return
    lookup=defaultdict(list)
    for e in self.epgs:
        if source_filter in ('All',e['source']):lookup[e['id']].append(e)
    win=tk.Toplevel(self.root);win.title('Category EPG Preview — '+group);win.geometry('1280x760')
    top=ttk.Frame(win,padding=10);top.pack(fill='x')
    ttk.Label(top,text=group,font=('Segoe UI',15,'bold')).pack(anchor='w')
    ttk.Label(top,text=f'{len(indices):,} playlist channels · Country: {ct} · EPG source filter: {source_filter} · Double-click a channel to view its full programme preview.',wraplength=1150).pack(anchor='w')
    ttk.Label(top,text='Schedules shown are imported XMLTV data. Unlinked channels only show a preview when their original tvg-id resolves uniquely; no automatic linking occurs.',wraplength=1150).pack(anchor='w')
    frame=ttk.Frame(win,padding=8);frame.pack(fill='both',expand=True)
    cols=('number','name','stream','id','source','status','start','programme')
    tree=ttk.Treeview(frame,columns=cols,show='headings',selectmode='browse')
    for key,label,width in [('number','#',55),('name','Playlist channel',240),('stream','Stream ID',100),('id','XMLTV ID',165),('source','EPG source',175),('status','Status',135),('start','First programme',170),('programme','Programme title',350)]:
        tree.heading(key,text=label);tree.column(key,width=width,stretch=key in ('name','programme'))
    ys=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);xs=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview)
    tree.configure(yscrollcommand=ys.set,xscrollcommand=xs.set)
    tree.grid(row=0,column=0,sticky='nsew');ys.grid(row=0,column=1,sticky='ns');xs.grid(row=1,column=0,sticky='ew');frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
    resolved={}
    for i in indices:
        c=self.playlist[i];cid=self.links.get(i) or c['id'];chosen=None
        options=lookup.get(cid,[]) if cid else []
        if i in self.links:
            options=[e for e in options if e['source']==self.link_sources.get(i)]
            status='Linked' if options else 'Linked / EPG missing'
        elif len(options)==1:status='ID found (not linked)'
        elif len(options)>1:status='Ambiguous source'
        else:status='No matching EPG'
        if len(options)==1:chosen=options[0];resolved[str(i)]=chosen
        first=chosen['listings'][0] if chosen and chosen.get('listings') else None
        tree.insert('','end',iid=str(i),values=(i+1,c['name'],c.get('stream_id',''),cid,chosen['source'] if chosen else (self.link_sources.get(i,'') if i in self.links else ', '.join(e['source'] for e in options[:2])),status,xmltv_local_time(first[0]) if first else '',first[2] if first else ''))
    def open_selected(_=None):
        sel=tree.selection()
        if not sel:return
        idx=sel[0];e=resolved.get(idx)
        if e:self.preview_epg(int(idx),e)
        else:messagebox.showinfo('No unique EPG','This channel has no uniquely resolved EPG in the selected source. Link it or filter to one EPG source first.',parent=win)
    tree.bind('<Double-1>',open_selected)
    ttk.Button(win,text='Preview Selected Channel',command=open_selected).pack(anchor='e',padx=12,pady=8)

 def link(self):
    i=self.selected_p();j=self.selected_e()
    if i is None or j is None:messagebox.showwarning('Select both','Select a playlist channel and an EPG channel.');return
    self.links[i]=self.epgs[j]['id'];self.link_sources[i]=self.epgs[j]['source'];self.refresh()
 def unlink(self):
    i=self.selected_p()
    if i is not None:self.links.pop(i,None);self.link_sources.pop(i,None);self.refresh()
 def bulk_preview(self):
    i=self.selected_p();j=self.selected_e()
    if i is None or j is None:messagebox.showwarning('Select both','Select the FIRST playlist game and its matching FIRST EPG channel.');return
    p=self.playlist[i];e=self.epgs[j];pn=league_number(p['name']);en=league_number(e['name']);im=IDNUM.match(e['id'])
    if not pn or not im:messagebox.showwarning('Unsupported pattern','Bulk linking requires a numbered sports playlist channel and a numeric XMLTV ID such as 123.MLB.');return
    if self.source_filter.get()!='All' and e['source']!=self.source_filter.get():return
    if en and en!=pn:messagebox.showerror('Mismatch','Selected EPG name identifies a different game number or league.');return
    base=int(im.group(1));suffix=im.group(2);basegame=pn[1];maxgame=tk.simpledialog.askinteger('Bulk range',f"Match {pn[0]} GAME {basegame:02d} to {e['id']}.\nEnter LAST game number to link:",initialvalue=basegame+9,minvalue=basegame,maxvalue=999,parent=self.root)
    if maxgame is None:return
    epg_ids={x['id'] for x in self.epgs if x['source']==e['source']};proposal=[];problems=[]
    for game in range(basegame,maxgame+1):
        matches=[(k,ch) for k,ch in enumerate(self.playlist) if league_number(ch['name'])==(pn[0],game) and ch['country']==p['country'] and ch['group']==p['group']]
        if len(matches)!=1:problems.append(f'GAME {game:02d}: {len(matches)} matching playlist channels');continue
        k,ch=matches[0];target=f'{base+game-basegame}{suffix}'
        if target not in epg_ids:problems.append(f'GAME {game:02d}: {target} not present in imported EPG');continue
        known=[x for x in self.epgs if x['id']==target and x['source']==e['source']];identified=[league_number(x['name']) for x in known if league_number(x['name'])]
        if identified and any(v!=(pn[0],game) for v in identified):problems.append(f'GAME {game:02d}: EPG name conflicts with {target}');continue
        if k in self.links and (self.links[k]!=target or self.link_sources.get(k)!=e['source']):problems.append(f'GAME {game:02d}: existing link {self.links[k]} would be replaced');continue
        proposal.append((k,target))
    preview='\n'.join(f"{self.playlist[k]['name']}  →  {target}" for k,target in proposal[:35]);errors='\n'.join(problems[:20])
    if not proposal:messagebox.showwarning('No safe links',errors or 'No matches');return
    msg=f'PROPOSED LINKS ({len(proposal)}):\n{preview}\n\nSKIPPED ({len(problems)}):\n{errors}\n\nApply these links?\n\nThis only updates the in-app mapping. Export to save.'
    if messagebox.askyesno('Review bulk sequence',msg):self.undo.append({k:(self.links.get(k),self.link_sources.get(k)) for k,_ in proposal});self.links.update(proposal);self.link_sources.update({k:e['source'] for k,_ in proposal});self.refresh()
 def undo_bulk(self):
    if not self.undo:return
    prev=self.undo.pop()
    for k,(v,source) in prev.items():
        if v is None:self.links.pop(k,None)
        else:self.links[k]=v
        if source is None:self.link_sources.pop(k,None)
        else:self.link_sources[k]=source
    self.refresh()
 def copy_ids(self):
    i=self.selected_p()
    if i is None:return
    c=self.playlist[i]
    result=f"Playlist channel #: {i+1}\nChannel: {c['name']}\nStream channel ID: {c.get('stream_id') or '(not detectable)'}\nPlaylist tvg-id: {c['id'] or '(blank)'}\nLinked XMLTV ID: {self.links.get(i) or '(none)'}\nEPG Source: {self.link_sources.get(i) or '(none)'}"
    self.root.clipboard_clear();self.root.clipboard_append(result)
    messagebox.showinfo('Copied','Channel identifiers copied to clipboard (without stream URL or credentials).')
 def export_ids(self):
    if not self.playlist:return
    path=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV','*.csv')],initialfile='channel_id_audit.csv')
    if not path:return
    with open(path,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['playlist_number','channel_name','game_number','country','group','stream_channel_id','playlist_tvg_id','linked_xmltv_id','epg_source'])
        for i in (self.filtered if self.filtered else range(len(self.playlist))):
            w.writerow([i+1,self.playlist[i]['name'],(league_number(self.playlist[i]['name']) or ('',''))[1],*[safe_csv(x) for x in channel_id_record(self.playlist[i],self.links.get(i,''))[1:]],self.link_sources.get(i,'')])
    messagebox.showinfo('Saved','Exported channel IDs without stream URLs or credentials.')
 def export_github_matches(self):
    """Export approved mappings only, without URLs or Xtream credentials."""
    if not self.links:
        messagebox.showinfo('GitHub export','Approve some matches before exporting.');return
    p=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV','*.csv')],initialfile='approved_matches.csv')
    if not p:return
    fields=['group','playlist_channel','original_tvg_id','source','source_channel_id','stream_id']
    written=0;skipped=[]
    with open(p,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for i in sorted(self.links):
            if i>=len(self.playlist):continue
            c=self.playlist[i];source=self.link_sources.get(i,'')
            if not source:skipped.append(c['name']);continue
            name=source.lower()
            if 'epg2' in name:src='epg2'
            elif 'epg37' in name:src='epg37'
            else:skipped.append(c['name']+' (unsupported source '+source+')');continue
            w.writerow({'group':c.get('group',''),'playlist_channel':c['name'],
                        'original_tvg_id':c.get('id',''),'source':src,
                        'source_channel_id':self.links[i], 'stream_id':c.get('stream_id','')})
            written+=1
    messagebox.showinfo('My-EPG-v2 export',f'Exported {written} approved mappings to\n{p}\n\nSkipped {len(skipped)} mappings with unsupported or missing EPG source.\nUpload as approved_matches.csv to the root of your GitHub repository.\nNo stream URLs or passwords were exported.')
 def save_links(self):
    p=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV','*.csv')],initialfile='iptv_epg_matches.csv')
    if not p:return
    with open(p,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['channel_name','country','group','original_tvg_id','xmltv_id','epg_source','stream_url'])
        for i,c in enumerate(self.playlist):
            if i in self.links:w.writerow([c['name'],c['country'],c['group'],c['id'],self.links[i],self.link_sources.get(i,''),c['url']])
    messagebox.showinfo('Saved',f'Exported {len(self.links)} mappings. This is a review/export CSV; adapt it to your build_epg.py matching schema before importing.')
 def load_links(self):
    p=filedialog.askopenfilename(filetypes=[('CSV','*.csv')]);
    if not p:return
    with open(p,encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    byurl={x['url']:i for i,x in enumerate(self.playlist)};byname=defaultdict(list)
    for i,x in enumerate(self.playlist):byname[(x['name'],x['group'])].append(i)
    n=0
    for r in rows:
        idx=byurl.get(r.get('stream_url',''))
        if idx is None:
            matches=byname[(r.get('channel_name',''),r.get('group',''))];idx=matches[0] if len(matches)==1 else None
        if idx is not None and r.get('xmltv_id'):
            source=r.get('epg_source','')
            options=[x for x in self.epgs if x['id']==r['xmltv_id'] and (not source or x['source']==source)]
            if len({x['source'] for x in options})!=1:continue
            self.links[idx]=r['xmltv_id'];self.link_sources[idx]=options[0]['source'];n+=1
    self.refresh();messagebox.showinfo('Imported',f'Loaded {n} matches.')
 def export_m3u(self):
    if not self.playlist:return
    p=filedialog.asksaveasfilename(defaultextension='.m3u',filetypes=[('M3U','*.m3u')],initialfile='linked_playlist_COPY.m3u')
    if not p:return
    def esc(s):return (s or '').replace('"','')
    with open(p,'w',encoding='utf-8') as f:
        f.write('#EXTM3U\n')
        for i,c in enumerate(self.playlist):
            cid=self.links.get(i,c['id']);f.write(f'#EXTINF:-1 tvg-id="{esc(cid)}" tvg-name="{esc(c["name"])}" group-title="{esc(c["group"])}",{c["name"]}\n{c["url"]}\n')
    messagebox.showinfo('Exported',f'Created a separate M3U copy at {p}. Original playlist was not modified.')

 def _backup_state(self):
    return {'links':dict(self.links),'link_sources':dict(self.link_sources)}
 def _apply_state(self,data):
    self.links={int(k):v for k,v in data.get('links',{}).items() if int(k)<len(self.playlist)}
    self.link_sources={int(k):v for k,v in data.get('link_sources',{}).items() if int(k)<len(self.playlist)}
    self.refresh()
 def backup_mappings(self):
    p=filedialog.asksaveasfilename(defaultextension='.json',initialfile='epg_mappings_backup.json',filetypes=[('JSON','*.json')]);
    if p:Path(p).write_text(json.dumps({'version':2,'playlist_fingerprint':self._fingerprint(),'state':self._backup_state()},indent=2),encoding='utf-8');messagebox.showinfo('Backup','Saved mapping backup without credentials or stream URLs.')
 def restore_backup(self):
    p=filedialog.askopenfilename(filetypes=[('JSON','*.json')]);
    if not p:return
    data=json.loads(Path(p).read_text(encoding='utf-8'))
    if data.get('playlist_fingerprint')!=self._fingerprint():messagebox.showerror('Playlist mismatch','This backup belongs to a different playlist/order. No links restored.');return
    self.undo.append({k:(self.links.get(k),self.link_sources.get(k)) for k in self.links});self._apply_state(data['state'])
 def _fingerprint(self):
    import hashlib
    return hashlib.sha256('\n'.join(f"{c['name']}|{c.get('stream_id','')}|{c['group']}" for c in self.playlist).encode()).hexdigest()
 def save_project(self):
    p=filedialog.asksaveasfilename(defaultextension='.json',initialfile='iptv_epg_project.json',filetypes=[('JSON','*.json')]);
    if not p:return
    # Projects deliberately do not store stream URLs, Xtream credentials, or raw programme descriptions.
    project={'version':2,'playlist_path':self.playlist_path,'playlist_fingerprint':self._fingerprint(),'epg_paths':self.epg_paths,'playlist_metadata':[{k:v for k,v in c.items() if k!='url'} for c in self.playlist], 'state':self._backup_state(),'enabled_groups':sorted(self.enabled_groups) if self.enabled_groups is not None else None,'country':self.ct.get(),'category':self.group_filter.get()}
    Path(p).write_text(json.dumps(project,indent=2),encoding='utf-8');self.project_path=p
    messagebox.showinfo('Project saved','Saved mappings, playlist metadata and EPG source paths. Stream URLs and Xtream credentials are not saved. Reconnect Xtream after reopening if needed.')
 def open_project(self):
    p=filedialog.askopenfilename(filetypes=[('JSON','*.json')]);
    if not p:return
    data=json.loads(Path(p).read_text(encoding='utf-8'))
    if data.get('version')!=2:messagebox.showerror('Project','Unsupported project format.');return
    def load():
        pl=data.get('playlist_path','')
        if pl and Path(pl).exists():rows=parse_m3u(pl)
        else:rows=[dict(c,url='') for c in data.get('playlist_metadata',[])]
        sources={};all_epgs=[]
        for name,path in data.get('epg_paths',{}).items():
            if path.startswith(('http://','https://')) or Path(path).exists():
                try:
                    loaded=parse_epg(path)
                    for e in loaded:e['source']=name
                    all_epgs.extend(loaded);sources[name]=path
                except Exception:pass
        return rows,all_epgs,sources
    def loaded(result):
        rows,epgs,sources=result;self.set_m3u(rows);self.epgs=epgs;self.epg_paths=sources;self.playlist_path=data.get('playlist_path','');self.project_path=p
        self.source_cb['values']=['All']+sorted({e['source'] for e in epgs});self.enabled_groups=set(data['enabled_groups']) if data.get('enabled_groups') is not None else None
        if self._fingerprint()==data.get('playlist_fingerprint'):self._apply_state(data['state'])
        else:messagebox.showwarning('Playlist changed','Playlist order changed; mappings were not restored.')
        self.ct.set(data.get('country','All'));self.group_filter.set(data.get('category','All'));self.refresh()
        messagebox.showinfo('Project',f'Loaded {len(rows):,} channels and {len(epgs):,} EPG channels. Missing sources are skipped. Xtream streams require reconnection.')
    self.work(load,loaded)
 def select_visible(self):
    rows=self.pt.get_children()
    if rows:self.pt.selection_set(rows)
 def batch_smart_match(self):
    """Score only highlighted playlist rows and review individual Yes/No decisions."""
    selected=sorted({int(x) for x in self.pt.selection()})
    if not selected:
        messagebox.showinfo('Select channels','Use Ctrl+click or Shift+click to select multiple playlist channels, then click Batch Smart Match Selected.')
        return
    if not self.epgs:
        messagebox.showwarning('EPG required','Import at least one XMLTV source first.')
        return
    # Build indexes once; avoid comparing every selected channel to every EPG entry.
    by_id=defaultdict(list);by_name=defaultdict(list);by_game=defaultdict(list)
    source=self.source_filter.get()
    for j,e in enumerate(self.epgs):
        if source!='All' and e['source']!=source:continue
        by_id[e['id']].append(j)
        by_name[norm(e['name'])].append(j)
        g=league_number(e['name'])
        if g:by_game[g].append(j)
    proposals=[]
    for i in selected:
        if i in self.links:continue  # Never silently overwrite approved links.
        p=self.playlist[i]
        candidates=set(by_id.get(p['id'],()))|set(by_name.get(norm(p['name']),()))
        g=league_number(p['name'])
        if g:candidates.update(by_game.get(g,()))
        ranked=sorted(((self.score(p,self.epgs[j]),j) for j in candidates if self.epgs[j]['count']>0),reverse=True)
        if not ranked:proposals.append({'i':i,'j':None,'score':0,'decision':'No candidate'});continue
        score,j=ranked[0]
        ambiguous=len(ranked)>1 and ranked[1][0]==score
        if score<70 or ambiguous:
            proposals.append({'i':i,'j':j,'score':score,'decision':'Ambiguous' if ambiguous else 'Low confidence'})
        else:proposals.append({'i':i,'j':j,'score':score,'decision':'Pending'})
    if not proposals:
        messagebox.showinfo('Already linked','All selected channels already have approved links. Unlink them first if you want to rematch.')
        return
    win=tk.Toplevel(self.root);win.title('Batch Smart Match — Approve or Reject Each Channel');win.geometry('1240x680')
    ttk.Label(win,text='Click YES or NO in each row, or highlight several rows and use the buttons below. Only YES rows are saved. A score is not proof of the correct programme.',wraplength=1190,padding=10).pack(anchor='w')
    frame=ttk.Frame(win);frame.pack(fill='both',expand=True,padx=10)
    cols=('channel','epg','source','score','decision','yes','no')
    tree=ttk.Treeview(frame,columns=cols,show='headings',selectmode='extended')
    for key,title,width in [('channel','Playlist Channel',325),('epg','Suggested EPG Channel / ID',340),('source','Source',150),('score','Score',65),('decision','Decision',115),('yes','YES ✓',75),('no','NO ✗',75)]:
        tree.heading(key,text=title);tree.column(key,width=width,stretch=key in ('channel','epg'))
    tree.tag_configure('yes',background='#dff3e5');tree.tag_configure('no',background='#ffe0df');tree.tag_configure('pending',background='#fff1cc')
    scroll=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);tree.configure(yscrollcommand=scroll.set)
    tree.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
    def paint(n):
        item=proposals[n];j=item['j'];e=self.epgs[j] if j is not None else None
        label=(e['name']+'  ['+e['id']+']') if e else '(No EPG candidate)'
        decision=item['decision'];tag='yes' if decision=='YES' else 'no' if decision=='NO' else 'pending'
        tree.item(str(n),values=(self.playlist[item['i']]['name'],label,e['source'] if e else '',item['score'],decision,'[ YES ]' if e else '—','[ NO ]'),tags=(tag,))
    for n in range(len(proposals)):
        tree.insert('','end',iid=str(n));paint(n)
    info=tk.StringVar()
    def summary():
        counts=Counter(x['decision'] for x in proposals)
        info.set(f"Selected: {len(selected):,} | Suggestions: {len(proposals):,} | YES: {counts['YES']:,} | NO: {counts['NO']:,} | Awaiting review: {len(proposals)-counts['YES']-counts['NO']:,}")
    def decide(indices,answer):
        for n in indices:
            item=proposals[n]
            if answer=='YES' and item['j'] is None:continue
            item['decision']=answer;paint(n)
        summary()
    def cell_click(event):
        row=tree.identify_row(event.y);column=tree.identify_column(event.x)
        if row and column in ('#6','#7'):
            decide([int(row)],'YES' if column=='#6' else 'NO')
            return 'break'
    tree.bind('<Button-1>',cell_click)
    buttons=ttk.Frame(win,padding=8);buttons.pack(fill='x')
    ttk.Label(buttons,textvariable=info).pack(side='left',padx=5)
    ttk.Button(buttons,text='YES for Highlighted',command=lambda:decide([int(x) for x in tree.selection()],'YES')).pack(side='left',padx=4)
    ttk.Button(buttons,text='NO for Highlighted',command=lambda:decide([int(x) for x in tree.selection()],'NO')).pack(side='left',padx=4)
    def approve_high_confidence():
        decide([n for n,x in enumerate(proposals) if x['score']>=95 and x['decision']=='Pending'],'YES')
    ttk.Button(buttons,text='YES Exact Matches (95+)',command=approve_high_confidence).pack(side='left',padx=4)
    def commit():
        chosen=[x for x in proposals if x['decision']=='YES' and x['j'] is not None]
        pending=[x for x in proposals if x['decision'] not in ('YES','NO')]
        if not chosen:messagebox.showinfo('No approvals','Click YES for at least one suggested match.',parent=win);return
        if not messagebox.askyesno('Apply reviewed matches',f'Apply {len(chosen):,} YES approvals?\n{len(pending):,} undecided suggestions will be skipped.\nYou can undo this batch using Undo Last Bulk Link.',parent=win):return
        self.undo.append({x['i']:(self.links.get(x['i']),self.link_sources.get(x['i'])) for x in chosen})
        for x in chosen:
            e=self.epgs[x['j']];self.links[x['i']]=e['id'];self.link_sources[x['i']]=e['source']
        self.refresh();win.destroy()
    ttk.Button(buttons,text='Apply YES Matches',command=commit).pack(side='right',padx=4)
    ttk.Button(buttons,text='Cancel',command=win.destroy).pack(side='right',padx=4)
    summary()
 def smart_match(self):
    if not self.playlist or not self.epgs:return
    # Indexed candidates avoid O(playlist * EPG) scoring for large lists.
    by_id=defaultdict(list);by_name=defaultdict(list);by_game=defaultdict(list)
    for j,e in enumerate(self.epgs):
        by_id[e['id']].append(j);by_name[norm(e['name'])].append(j)
        g=league_number(e['name'])
        if g:by_game[g].append(j)
    proposals=[]
    for i,p in enumerate(self.playlist):
        if i in self.links:continue
        indices=set(by_id.get(p['id'],[]))|set(by_name.get(norm(p['name']),[]))
        g=league_number(p['name'])
        if g:indices.update(by_game.get(g,[]))
        scores=sorted(((self.score(p,self.epgs[j]),j) for j in indices if self.epgs[j]['count']>0),reverse=True)
        if scores and scores[0][0]>=85 and (len(scores)==1 or scores[0][0]>scores[1][0]):
            score,j=scores[0];proposals.append((i,j,score))
    win=tk.Toplevel(self.root);win.title('Smart Match — Review Suggestions');win.geometry('1050x650')
    ttk.Label(win,text=f'{len(proposals):,} unique high-confidence suggestions. No links applied until you approve. Scores describe name/ID similarity, NOT verified game content.',wraplength=1000,padding=8).pack(anchor='w')
    tree=ttk.Treeview(win,columns=('iptv','epgid','epg','score'),show='headings',selectmode='extended')
    for k,w in [('iptv',330),('epgid',190),('epg',280),('score',80)]:tree.heading(k,text=k);tree.column(k,width=w)
    tree.pack(fill='both',expand=True,padx=8)
    for n,(i,j,score) in enumerate(proposals):tree.insert('','end',iid=str(n),values=(self.playlist[i]['name'],self.epgs[j]['id'],self.epgs[j]['source'],score))
    def apply():
        chosen=[proposals[int(x)] for x in tree.selection()]
        if not chosen:return
        self.undo.append({i:(self.links.get(i),self.link_sources.get(i)) for i,_,_ in chosen})
        for i,j,_ in chosen:self.links[i]=self.epgs[j]['id'];self.link_sources[i]=self.epgs[j]['source']
        self.refresh();win.destroy()
    ttk.Button(win,text='Approve Selected Matches',command=apply).pack(pady=8)
 def _date_utc(self,raw):
    try:
        raw=raw.strip();dt=datetime.strptime(raw[:14],'%Y%m%d%H%M%S');off=raw[14:].strip()
        if re.fullmatch(r'[+-]\d{4}',off):dt=datetime.strptime(raw[:14]+' '+off,'%Y%m%d%H%M%S %z')
        else:dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError,AttributeError):return None
 def coverage_report(self):
    if not self.playlist:return
    now=datetime.now(timezone.utc);epgs={(e['source'],e['id']):e for e in self.epgs};report=[]
    for i,c in enumerate(self.playlist):
        e=epgs.get((self.link_sources.get(i),self.links.get(i)))
        if not e:report.append((i,'No approved EPG',0,0,0));continue
        windows=[]
        for hrs in (24,48,72):
            end=now+timedelta(hours=hrs)
            matches=[x for x in e['listings'] if (self._date_utc(x[1]) or now-timedelta(days=365))>now and (self._date_utc(x[0]) or end+timedelta(days=365))<end]
            windows.append(sum(1 for x in matches if not re.search(r'^(signing off|no event|to be announced|tba)$',x[2].strip(),re.I)))
        report.append((i,'Sampled (first 60 listings)' if e['count']>60 else 'Complete',*windows))
    p=filedialog.asksaveasfilename(defaultextension='.csv',initialfile='epg_coverage.csv',filetypes=[('CSV','*.csv')]);
    if not p:return
    with open(p,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['playlist_number','channel_name','xmltv_id','source','coverage_status','programmes_24h','programmes_48h','programmes_72h'])
        for i,status,*counts in report:w.writerow([i+1,self.playlist[i]['name'],self.links.get(i,''),self.link_sources.get(i,''),status,*counts])
    messagebox.showinfo('Coverage','Coverage report exported. Counts are based on up to 60 sampled programmes per EPG channel; channels marked Sampled are not exhaustive.')
 def compare_epgs(self):
    i=self.selected_p()
    if i is None:messagebox.showinfo('Compare','Select an IPTV channel first.');return
    p=self.playlist[i];candidates=sorted(((self.score(p,e),e) for e in self.epgs if self.score(p,e)>=50),key=lambda x:-x[0])[:30]
    win=tk.Toplevel(self.root);win.title('Compare EPG Sources — '+p['name']);win.geometry('1100x650')
    tree=ttk.Treeview(win,columns=('score','source','id','name','count','first'),show='headings')
    for k,w in [('score',65),('source',180),('id',190),('name',250),('count',90),('first',360)]:tree.heading(k,text=k);tree.column(k,width=w)
    tree.pack(fill='both',expand=True)
    for n,(score,e) in enumerate(candidates):tree.insert('','end',iid=str(n),values=(score,e['source'],e['id'],e['name'],e['count'],e['listings'][0][2] if e['listings'] else ''))
    ttk.Label(win,text='Select a row and preview its programme listings. Matching scores do not prove broadcast identity.').pack(anchor='w',padx=10)
    def preview():
        sel=tree.selection()
        if sel:self.preview_epg(i,candidates[int(sel[0])][1])
    ttk.Button(win,text='Preview Selected Source',command=preview).pack(pady=8)
 def _read_programmes(self,path,needed):
    # Stream XML rather than retaining all programmes in memory.
    with open_source(path) as f:
        for _,el in ET.iterparse(f,events=('end',)):
            if el.tag=='programme':
                if el.get('channel') in needed:yield copy.deepcopy(el)
                el.clear()
            elif el.tag=='channel':el.clear()
 def generate_guide(self):
    if not self.links:messagebox.showinfo('Export','Approve channel matches before exporting.');return
    missing=[s for s in set(self.link_sources.values()) if s not in self.epg_paths]
    if missing:messagebox.showerror('Missing source paths','Cannot export because these EPG sources must be re-imported: '+', '.join(missing));return
    p=filedialog.asksaveasfilename(defaultextension='.xml.gz',initialfile='combined_epg.xml.gz',filetypes=[('XMLTV GZip','*.xml.gz')]);
    if not p:return
    def build():
        mapping=defaultdict(lambda:defaultdict(list))
        for i,cid in self.links.items():
            source=self.link_sources.get(i)
            if source in self.epg_paths and i<len(self.playlist):mapping[source][cid].append(i)
        # One channel per playlist entry: distinct IDs avoid collisions when different sources share an XMLTV ID.
        with gzip.open(p,'wb',compresslevel=6) as out:
            out.write(b'<?xml version="1.0" encoding="utf-8"?>\n<tv generator-info-name="IPTV EPG Manager 2.0">\n')
            for i in sorted({i for ids in mapping.values() for targets in ids.values() for i in targets}):
                c=self.playlist[i];ch=ET.Element('channel',{'id':f'iptv.{i+1}'})
                ET.SubElement(ch,'display-name').text=c['name']
                if c.get('logo'):ET.SubElement(ch,'icon',{'src':c['logo']})
                out.write(ET.tostring(ch,encoding='utf-8')+b'\n')
            count=0
            for source,ids in mapping.items():
                for el in self._read_programmes(self.epg_paths[source],set(ids)):
                    for i in ids[el.get('channel')]:
                        item=copy.deepcopy(el);item.set('channel',f'iptv.{i+1}')
                        out.write(ET.tostring(item,encoding='utf-8')+b'\n');count+=1
            out.write(b'</tv>\n')
        return count
    def done(n):messagebox.showinfo('XMLTV generated',f'Exported {n:,} programme entries. IMPORTANT: channel IDs are iptv.1, iptv.2 etc. TiviMate requires a matching exported M3U; use Export TiviMate Pair to generate both together.')
    self.work(build,done)
 def export_tivimate_pair(self):
    # Generates a playlist matching iptv.N IDs and guide; keep source playlist unchanged.
    if not self.playlist:return
    p=filedialog.asksaveasfilename(defaultextension='.m3u',initialfile='tivimate_matched_COPY.m3u',filetypes=[('M3U','*.m3u')]);
    if not p:return
    with open(p,'w',encoding='utf-8') as f:
        f.write('#EXTM3U\n')
        for i,c in enumerate(self.playlist):
            cid=f'iptv.{i+1}' if i in self.links else c['id']
            esc=lambda s:str(s or '').replace('"','')
            f.write(f'#EXTINF:-1 tvg-id="{esc(cid)}" tvg-name="{esc(c["name"])}" group-title="{esc(c["group"])}" tvg-logo="{esc(c.get("logo",""))}",{c["name"]}\n{c["url"]}\n')
    messagebox.showinfo('Playlist exported','Exported companion playlist with iptv.N IDs. Generate XMLTV.GZ in the same session. This copy contains your private stream URLs; keep it secure.')
 def refresh_guides(self):
    if not self.epg_paths:return
    paths=dict(self.epg_paths);self._last_refresh=datetime.now(timezone.utc)
    def load():
        results=[];fail=[]
        for name,path in paths.items():
            try:
                loaded=parse_epg(path)
                for e in loaded:e['source']=name
                results.extend(loaded)
            except Exception as ex:fail.append(f'{name}: {type(ex).__name__}')
        return results,fail
    def done(result):
        rows,fail=result
        if rows:
            failed_names={x.split(':')[0] for x in fail}
            rows.extend(e for e in self.epgs if e['source'] in failed_names)
            self.epgs=rows
        if rows:self.source_cb['values']=['All']+sorted({e['source'] for e in rows});self.refresh()
        if fail:messagebox.showwarning('Refresh incomplete','Some sources failed; previous listings may have been replaced.\n'+'\n'.join(fail))
    self.work(load,done)
 def xtream_epg_compare(self):
    if not self.xtream_session:messagebox.showinfo('Xtream','Reconnect through Connect Xtream in this session to compare provider short EPG. Credentials are not stored in projects.');return
    i=self.selected_p()
    if i is None or not self.playlist[i].get('stream_id'):messagebox.showinfo('Xtream','Select a channel with a provider stream ID.');return
    server,user,password=self.xtream_session;sid=self.playlist[i]['stream_id']
    def fetch():return xtream_api(server,user,password,'get_short_epg',stream_id=sid,limit=12)
    def done(data):
        rows=data.get('epg_listings',[]) if isinstance(data,dict) else []
        win=tk.Toplevel(self.root);win.title('Xtream Provider EPG — '+self.playlist[i]['name']);win.geometry('850x550')
        text=tk.Text(win,wrap='word');text.pack(fill='both',expand=True)
        import base64
        for x in rows:
            title=x.get('title','');desc=x.get('description','')
            def decode(v):
                try:return base64.b64decode(v).decode('utf-8','replace')
                except Exception:return str(v)
            text.insert('end',f"{x.get('start','')} — {x.get('end','')}\n{decode(title)}\n{decode(desc)}\n\n")
        if not rows:text.insert('end','Provider returned no short EPG listings for this stream.')
        text.config(state='disabled')
    self.work(fetch,done)
 def show_logos(self):
    i=self.selected_p()
    if i is None:messagebox.showinfo('Artwork','Select a playlist channel first.');return
    c=self.playlist[i];e=next((e for e in self.epgs if e['id']==self.links.get(i) and e['source']==self.link_sources.get(i)),None)
    win=tk.Toplevel(self.root);win.title('Channel Logos and Artwork');win.geometry('800x250')
    for label,url in [('IPTV channel logo',c.get('logo','')),('Matched EPG logo',e.get('logo','') if e else '')]:
        ttk.Label(win,text=label+': '+(url or '(not supplied)'),wraplength=750,padding=8).pack(anchor='w')
        if url and url.startswith(('http://','https://')):ttk.Button(win,text='Open '+label,command=lambda u=url:webbrowser.open(u)).pack(anchor='w',padx=8)
    ttk.Label(win,text='Programme artwork is not universally available in XMLTV. External image URLs open in your browser.').pack(anchor='w',padx=8,pady=10)

 def _github_rows(self):
    rows=[];errors=[];seen={};valid={(e['source'],e['id']) for e in self.epgs}
    for i in sorted(self.links):
        if i>=len(self.playlist):continue
        c=self.playlist[i];srcname=self.link_sources.get(i,'');low=srcname.lower()
        src='epg2' if 'epg2' in low else 'epg37' if 'epg37' in low else None
        if not src:
            errors.append(f"{c['name']}: unsupported EPG source {srcname}");continue
        if (srcname,self.links[i]) not in valid:
            errors.append(f"{c['name']}: approved EPG ID not found in imported source");continue
        row={'group':c.get('group',''),'playlist_channel':c['name'],'original_tvg_id':c.get('id',''),'source':src,'source_channel_id':self.links[i],'stream_id':c.get('stream_id','')}
        key=(row['group'].casefold(),row['playlist_channel'].casefold(),row['original_tvg_id'].casefold(),row['stream_id'])
        val=(src,row['source_channel_id'])
        if key in seen and seen[key]!=val:errors.append(f"Conflicting approved links: {c['name']}");continue
        seen[key]=val;rows.append(row)
    return rows,errors
 def _github_csv(self,rows):
    output=io.StringIO(newline='');writer=csv.DictWriter(output,fieldnames=['group','playlist_channel','original_tvg_id','source','source_channel_id','stream_id'],lineterminator='\n');writer.writeheader();writer.writerows(rows)
    return output.getvalue().encode('utf-8')
 def _github_request(self,method,url,token,data=None):
    if not url.startswith('https://api.github.com/'):raise ValueError('Unexpected GitHub API address')
    headers={'Accept':'application/vnd.github+json','Authorization':'Bearer '+token,'X-GitHub-Api-Version':'2022-11-28','User-Agent':'IPTV-EPG-Manager-v2.2'}
    payload=json.dumps(data).encode() if data is not None else None
    if payload:headers['Content-Type']='application/json'
    req=urllib.request.Request(url,data=payload,headers=headers,method=method)
    try:
        with urllib.request.urlopen(req,timeout=35) as resp:
            body=resp.read(3*1024*1024)
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as ex:
        body=ex.read(1500).decode('utf-8','replace')
        raise RuntimeError(f'GitHub API HTTP {ex.code}: {body}') from None
 def github_dashboard(self):
    win=tk.Toplevel(self.root);win.title('My-EPG-v2 GitHub Sync & Build Status');win.geometry('850x660')
    outer=ttk.Frame(win,padding=12);outer.pack(fill='both',expand=True)
    ttk.Label(outer,text='My-EPG-v2 · GitHub Sync',font=('Segoe UI',15,'bold')).pack(anchor='w')
    ttk.Label(outer,text='Token stays in memory only. Use a fine-grained token with Contents: Read/Write and Actions: Read/Write on this repository.',wraplength=790).pack(anchor='w',pady=6)
    repo=tk.StringVar(value='55Corndog1337/My-EPG-v2');branch=tk.StringVar(value='main');workflow=tk.StringVar(value='');token=tk.StringVar()
    for name,var,secret in [('Repository (owner/repo)',repo,False),('Branch',branch,False),('Workflow filename (optional; leave blank to rely on push trigger)',workflow,False),('GitHub fine-grained token',token,True)]:
        ttk.Label(outer,text=name).pack(anchor='w');ttk.Entry(outer,textvariable=var,show='*' if secret else '',width=80).pack(anchor='w',fill='x',pady=(0,5))
    status=tk.Text(outer,height=14,wrap='word');status.pack(fill='both',expand=True,pady=8)
    def log(msg):status.insert('end',str(msg)+'\n');status.see('end')
    def target():
        value=repo.get().strip()
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',value):raise ValueError('Repository must be owner/repo')
        if not re.fullmatch(r'[A-Za-z0-9_./-]+',branch.get().strip()):raise ValueError('Invalid branch')
        if not token.get().strip():raise ValueError('Enter a GitHub token')
        return 'https://api.github.com/repos/'+value,branch.get().strip(),token.get().strip()
    def run(fn):
        try:base,ref,key=target()
        except Exception as ex:messagebox.showerror('GitHub',str(ex),parent=win);return
        def work():return fn(base,ref,key)
        def done(result):log(result)
        self.work(work,done)
    def check(base,ref,key):
        repo_info=self._github_request('GET',base,key)
        runs=self._github_request('GET',base+'/actions/runs?per_page=5',key)
        lines=[f"Repository: {repo_info.get('full_name')}",f"Default branch: {repo_info.get('default_branch')}"]
        for item in runs.get('workflow_runs',[]):lines.append(f"{item.get('created_at')}  {item.get('name')}  {item.get('status')} / {item.get('conclusion')}  {item.get('html_url')}")
        return '\n'.join(lines)
    def sync(base,ref,key):
        rows,errors=self._github_rows()
        if errors:raise ValueError('Pre-sync validation failed; no upload made:\n'+'\n'.join(errors[:25]))
        if not rows:raise ValueError('No validated approved mappings to upload')
        raw=self._github_csv(rows);path=base+'/contents/approved_matches.csv';existing=None
        try:existing=self._github_request('GET',path+'?ref='+urllib.parse.quote(ref,safe=''),key)
        except RuntimeError as ex:
            if 'HTTP 404' not in str(ex):raise
        if existing and existing.get('content'):
            previous=base64.b64decode(existing['content']);
            if previous==raw:return f'Already up to date: {len(rows):,} approved mappings. No commit required.'
        backup=Path.home()/'Documents'/'IPTV_EPG_Backups';backup.mkdir(parents=True,exist_ok=True)
        stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
        if existing and existing.get('content'):(backup/f'github_approved_matches_before_{stamp}.csv').write_bytes(base64.b64decode(existing['content']))
        (backup/f'local_approved_matches_{stamp}.csv').write_bytes(raw)
        body={'message':f'Update {len(rows)} approved EPG mappings from IPTV EPG Manager v2.2','content':base64.b64encode(raw).decode(),'branch':ref}
        if existing and existing.get('sha'):body['sha']=existing['sha']
        result=self._github_request('PUT',path,key,body)
        note=f"Uploaded {len(rows):,} mappings; commit {result.get('commit',{}).get('sha','unknown')[:12]}. Local backup: {backup}"
        wf=workflow.get().strip()
        if wf:
            if not re.fullmatch(r'[A-Za-z0-9_.-]+\.ya?ml',wf):raise ValueError('Committed successfully, but workflow filename must end in .yml or .yaml')
            self._github_request('POST',base+'/actions/workflows/'+urllib.parse.quote(wf,safe='')+'/dispatches',key,{'ref':ref})
            note+='\nWorkflow dispatch requested: '+wf
        else:note+='\nWorkflow starts automatically only if your existing GitHub Actions YAML listens for pushes to this branch.'
        return note
    buttons=ttk.Frame(outer);buttons.pack(fill='x')
    ttk.Button(buttons,text='Check Build Status',command=lambda:run(check)).pack(side='left',padx=4)
    def confirm():
        rows,errors=self._github_rows()
        if errors:
            messagebox.showerror('Validation failed',f'{len(errors)} problems; nothing uploaded.\n'+'\n'.join(errors[:12]),parent=win);return
        if not messagebox.askyesno('Confirm GitHub upload',f'Upload {len(rows):,} approved mappings to {repo.get()}/{branch.get()}?\n\nThis commits approved_matches.csv to GitHub.',parent=win):return
        run(sync)
    ttk.Button(buttons,text='Validate & Sync to GitHub',command=confirm).pack(side='left',padx=4)
    ttk.Button(buttons,text='Open Repository',command=lambda:webbrowser.open('https://github.com/'+repo.get().strip())).pack(side='left',padx=4)
    ttk.Label(outer,text='For rollback, restore a CSV from Documents/IPTV_EPG_Backups by committing it to approved_matches.csv in GitHub. No automatic rollback of published guides.',wraplength=800).pack(anchor='w',pady=6)
 def detect_changes(self):
    if not self.playlist:messagebox.showinfo('Channel changes','Load a playlist or connect to Xtream first.');return
    p=filedialog.askopenfilename(title='Select a newly downloaded M3U to compare',filetypes=[('M3U','*.m3u'),('All files','*.*')]);
    if not p:return
    def work():return parse_m3u(p)
    def done(new):
        def key(c):return (c.get('stream_id') or '',c.get('name','').casefold(),c.get('group','').casefold())
        oldmap={key(c):c for c in self.playlist};newmap={key(c):c for c in new}
        added=[c for k,c in newmap.items() if k not in oldmap];removed=[c for k,c in oldmap.items() if k not in newmap]
        win=tk.Toplevel(self.root);win.title('Channel Lineup Changes');win.geometry('900x580')
        ttk.Label(win,text=f'New: {len(added):,}   Removed/renamed: {len(removed):,}. Existing matches are unchanged.',padding=10).pack(anchor='w')
        tree=ttk.Treeview(win,columns=('change','channel','category','stream'),show='headings')
        for c,w in [('change',120),('channel',350),('category',250),('stream',100)]:tree.heading(c,text=c);tree.column(c,width=w)
        tree.pack(fill='both',expand=True)
        for kind,items in [('Added',added),('Removed or renamed',removed)]:
            for c in items:tree.insert('','end',values=(kind,c['name'],c.get('group',''),c.get('stream_id','')))
        def export():
            dest=filedialog.asksaveasfilename(defaultextension='.csv',initialfile='channel_changes.csv',filetypes=[('CSV','*.csv')]);
            if dest:
                with open(dest,'w',newline='',encoding='utf-8-sig') as f:
                    writer=csv.writer(f);writer.writerow(['change','channel','category','stream_id']);[writer.writerow(tree.item(i,'values')) for i in tree.get_children()]
        ttk.Button(win,text='Export Change Report',command=export).pack(pady=8)
    self.work(work,done)
 def sports_assistant(self):
    if not self.playlist:return
    rows=[(i,c,league_number(c['name'])) for i,c in enumerate(self.playlist) if league_number(c['name'])]
    win=tk.Toplevel(self.root);win.title('Numbered Sports Feeds — Matching Review');win.geometry('1040x640')
    ttk.Label(win,text='Sports feed number matches are suggestions, not confirmation of the actual game being broadcast.',padding=10).pack(anchor='w')
    tree=ttk.Treeview(win,columns=('name','game','linked','source','status'),show='headings')
    for col,width in [('name',340),('game',110),('linked',220),('source',170),('status',130)]:tree.heading(col,text=col);tree.column(col,width=width)
    tree.pack(fill='both',expand=True)
    lookup=defaultdict(list)
    for e in self.epgs:lookup[e['id']].append(e)
    for i,c,game in rows:
        status,_=self.epg_status(i,lookup)
        tree.insert('','end',iid=str(i),values=(c['name'],str(game),self.links.get(i,''),self.link_sources.get(i,''),status))
    def select():
        chosen=tree.selection()
        if chosen:
            i=int(chosen[0]);self.status_filter.set('All');self.ct.set('All');self.group_filter.set('All');self.search.set('');self.refresh()
            if str(i) in self.pt.get_children():self.pt.selection_set(str(i));self.pt.see(str(i));self.selection_changed();win.destroy()
    ttk.Button(win,text='Review Selected Feed in Matcher',command=select).pack(pady=8)

if __name__=='__main__':
 from tkinter import simpledialog
 tk.simpledialog=simpledialog
 root=tk.Tk();Matcher(root);root.mainloop()
