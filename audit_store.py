import hashlib, os, re, sqlite3, threading, time
from datetime import datetime, timedelta

PROJECT_DIR=os.path.dirname(os.path.abspath(__file__))
LOG_DIR=os.path.join(PROJECT_DIR,'logs')
LOG_FILE=os.path.join(LOG_DIR,'audio_server.log')
DB_FILE=os.path.join(PROJECT_DIR,'audioserver.db')
_lock=threading.RLock()

LINE_RE=re.compile(r'^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:,\d+)? \| (?P<level>[^|]+) \| action=(?P<action>[^|]+) \| result=(?P<result>[^|]+) \| ?(?P<details>.*)$')
SOUND_RE=re.compile(r'(?:^|\s)sound=([^\s]+)')
SOURCE_RE=re.compile(r'(?:^|\s)source=([^\s]+)')


def _connect():
 con=sqlite3.connect(DB_FILE,timeout=10)
 con.row_factory=sqlite3.Row
 con.execute('PRAGMA journal_mode=WAL')
 con.execute('PRAGMA synchronous=NORMAL')
 return con


def init_db():
 with _lock,_connect() as con:
  con.executescript('''
  CREATE TABLE IF NOT EXISTS audit_events(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_time TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'INFO',
    action TEXT NOT NULL,
    result TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    sound TEXT,
    source TEXT,
    fingerprint TEXT NOT NULL UNIQUE
  );
  CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_events(event_time DESC);
  CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_events(action);
  CREATE INDEX IF NOT EXISTS idx_audit_sound ON audit_events(sound);
  ''')


def _parse(line):
 line=line.rstrip('\r\n')
 m=LINE_RE.match(line)
 if not m:return None
 details=m.group('details').strip()
 sm=SOUND_RE.search(details); src=SOURCE_RE.search(details)
 fingerprint=hashlib.sha256(line.encode('utf-8','replace')).hexdigest()
 return {
  'event_time':m.group('time'),'level':m.group('level').strip(),'action':m.group('action').strip(),
  'result':m.group('result').strip(),'details':details,
  'sound':sm.group(1) if sm else None,'source':src.group(1) if src else None,'fingerprint':fingerprint
 }


def ingest_line(line):
 event=_parse(line)
 if not event:return False
 try:
  with _lock,_connect() as con:
   con.execute('INSERT OR IGNORE INTO audit_events(event_time,level,action,result,details,sound,source,fingerprint) VALUES(?,?,?,?,?,?,?,?)',
    (event['event_time'],event['level'],event['action'],event['result'],event['details'],event['sound'],event['source'],event['fingerprint']))
  return True
 except Exception:return False


def bootstrap_logs():
 init_db()
 if not os.path.isdir(LOG_DIR):return
 names=sorted([n for n in os.listdir(LOG_DIR) if n.startswith('audio_server.log')])
 for name in names:
  path=os.path.join(LOG_DIR,name)
  try:
   with open(path,'r',encoding='utf-8',errors='replace') as f:
    for line in f:ingest_line(line)
  except OSError:pass


def tail_loop():
 bootstrap_logs(); offset=0; identity=None
 while True:
  try:
   if not os.path.exists(LOG_FILE):time.sleep(2);continue
   st=os.stat(LOG_FILE); current_identity=(getattr(st,'st_ino',0),st.st_ctime_ns)
   if identity!=current_identity or st.st_size<offset:
    identity=current_identity;offset=0
   with open(LOG_FILE,'r',encoding='utf-8',errors='replace') as f:
    f.seek(offset)
    for line in f:ingest_line(line)
    offset=f.tell()
  except Exception:pass
  time.sleep(2)


def recent_events(limit=250):
 limit=max(1,min(2000,int(limit)))
 with _lock,_connect() as con:
  rows=con.execute('SELECT id,event_time,level,action,result,details,sound,source FROM audit_events ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
 return [dict(r) for r in rows]


def metrics(days=7):
 days=max(1,min(365,int(days))); since=(datetime.now()-timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
 with _lock,_connect() as con:
  total=con.execute('SELECT COUNT(*) c FROM audit_events WHERE event_time>=?',(since,)).fetchone()['c']
  plays=con.execute("SELECT COUNT(*) c FROM audit_events WHERE event_time>=? AND action='queue_play' AND result='ok'",(since,)).fetchone()['c']
  errors=con.execute("SELECT COUNT(*) c FROM audit_events WHERE event_time>=? AND result='error'",(since,)).fetchone()['c']
  scheduled=con.execute("SELECT COUNT(*) c FROM audit_events WHERE event_time>=? AND action='queue_play' AND source='schedule' AND result='ok'",(since,)).fetchone()['c']
  manual=con.execute("SELECT COUNT(*) c FROM audit_events WHERE event_time>=? AND action='queue_play' AND source='manual' AND result='ok'",(since,)).fetchone()['c']
  top=con.execute("SELECT sound,COUNT(*) c FROM audit_events WHERE event_time>=? AND action='queue_play' AND result='ok' AND sound IS NOT NULL GROUP BY sound ORDER BY c DESC,sound LIMIT 10",(since,)).fetchall()
  daily=con.execute("SELECT substr(event_time,1,10) day,COUNT(*) c FROM audit_events WHERE event_time>=? AND action='queue_play' AND result='ok' GROUP BY substr(event_time,1,10) ORDER BY day",(since,)).fetchall()
 return {'days':days,'since':since,'events':total,'plays':plays,'errors':errors,'scheduled_plays':scheduled,'manual_plays':manual,'top_sounds':[dict(r) for r in top],'daily_plays':[dict(r) for r in daily]}


def database_info():
 try:size=os.path.getsize(DB_FILE)
 except OSError:size=0
 with _lock,_connect() as con:count=con.execute('SELECT COUNT(*) c FROM audit_events').fetchone()['c']
 return {'path':DB_FILE,'events':count,'size_bytes':size}
