from flask import Flask, request, jsonify, render_template
import hmac, json, logging, os, secrets, subprocess, threading, time
from collections import defaultdict, deque
from datetime import datetime
from logging.handlers import RotatingFileHandler
import pygame

PROJECT_DIR=os.path.dirname(os.path.abspath(__file__))
SOUNDS_FILE=os.path.join(PROJECT_DIR,'sounds.json'); TOKEN_FILE=os.path.join(PROJECT_DIR,'audio_server_token.txt')
SETTINGS_FILE=os.path.join(PROJECT_DIR,'local_settings.json'); LOG_DIR=os.path.join(PROJECT_DIR,'logs'); LOG_FILE=os.path.join(LOG_DIR,'audio_server.log')
app=Flask(__name__); pygame.mixer.init(); START_TIME=time.time(); lock=threading.Lock(); history=deque(maxlen=100); request_times=defaultdict(deque); current_sound=None

def setup_logging():
 os.makedirs(LOG_DIR,exist_ok=True); h=RotatingFileHandler(LOG_FILE,maxBytes=2*1024*1024,backupCount=5,encoding='utf-8'); h.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')); app.logger.setLevel(logging.INFO); app.logger.addHandler(h)
def load_json(path,default):
 try:
  with open(path,'r',encoding='utf-8') as f:return json.load(f)
 except (FileNotFoundError,json.JSONDecodeError):return default
def save_json(path,data):
 with open(path,'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
def load_token():
 t=os.environ.get('AUDIO_SERVER_TOKEN','').strip()
 if t:return t
 if os.path.exists(TOKEN_FILE):
  t=open(TOKEN_FILE,encoding='utf-8').read().strip()
  if t:return t
 t=secrets.token_urlsafe(32); open(TOKEN_FILE,'w',encoding='utf-8').write(t); return t
def version():
 try:return subprocess.run(['git','rev-parse','--short','HEAD'],cwd=PROJECT_DIR,capture_output=True,text=True,timeout=3,check=True).stdout.strip()
 except Exception:return 'unknown'
def ip():return request.remote_addr or 'unknown'
def add_history(action,result,details=''):
 item={'time':datetime.now().isoformat(timespec='seconds'),'ip':ip(),'action':action,'result':result,'details':details}; history.appendleft(item); app.logger.info('ip=%s | action=%s | result=%s | %s',ip(),action,result,details)
def auth():
 a=request.headers.get('Authorization',''); supplied=a[7:].strip() if a.startswith('Bearer ') else ''
 if not supplied or not hmac.compare_digest(supplied,TOKEN):return jsonify({'error':'Token de acesso invalido ou ausente'}),401
 return None
def save_settings():save_json(SETTINGS_FILE,SETTINGS)
def play_sound(name):
 global current_sound
 if name not in SOUNDS:return False,'Audio nao encontrado'
 path=SOUNDS[name]
 if not os.path.exists(path):return False,'Arquivo de audio nao encontrado'
 with lock:pygame.mixer.music.load(path); pygame.mixer.music.play(); current_sound=name
 return True,None

setup_logging(); SOUNDS=load_json(SOUNDS_FILE,{}); TOKEN=load_token(); SETTINGS=load_json(SETTINGS_FILE,{'volume':1.0,'maintenance':False,'allowed_ips':[],'schedules':[]}); pygame.mixer.music.set_volume(float(SETTINGS.get('volume',1.0)))

@app.before_request
def protection():
 if request.path.startswith('/static'):return None
 allowed=SETTINGS.get('allowed_ips',[])
 if allowed and ip() not in allowed and ip() not in ('127.0.0.1','::1'):return jsonify({'error':'IP nao autorizado'}),403
 q=request_times[ip()]; now=time.time()
 while q and now-q[0]>60:q.popleft()
 if len(q)>=120:return jsonify({'error':'Muitas requisicoes'}),429
 q.append(now)

@app.get('/')
def dashboard():return render_template('index.html')
@app.get('/status')
def status():
 busy=bool(pygame.mixer.music.get_busy())
 return jsonify({'status':'online','version':version(),'uptime_seconds':int(time.time()-START_TIME),'playing':busy,'current_sound':current_sound if busy else None,'volume':round(pygame.mixer.music.get_volume(),2),'sounds_count':len(SOUNDS),'requests_last_minute':sum(len(x) for x in request_times.values()),'maintenance':bool(SETTINGS.get('maintenance')),'security':'token+optional_ip_allowlist'})
@app.get('/sounds')
def sounds():return jsonify({'sounds':[{'name':n,'path_exists':os.path.exists(p)} for n,p in SOUNDS.items()]})
@app.get('/history')
def get_history():
 e=auth()
 if e:return e
 return jsonify({'history':list(history)})
@app.post('/play')
def play():
 e=auth()
 if e:return e
 if SETTINGS.get('maintenance'):return jsonify({'error':'Servidor em modo de manutencao'}),503
 name=(request.get_json(silent=True) or {}).get('sound'); ok,err=play_sound(name)
 if not ok:add_history('play','error',f'sound={name} error={err}'); return jsonify({'error':err}),404
 add_history('play','ok',f'sound={name}'); return jsonify({'status':'playing','sound':name,'behavior':'interrupts_current'})
@app.post('/stop')
def stop():
 e=auth()
 if e:return e
 pygame.mixer.music.stop(); add_history('stop','ok'); return jsonify({'status':'stopped'})
@app.post('/pause')
def pause():
 e=auth()
 if e:return e
 pygame.mixer.music.pause(); add_history('pause','ok'); return jsonify({'status':'paused'})
@app.post('/resume')
def resume():
 e=auth()
 if e:return e
 pygame.mixer.music.unpause(); add_history('resume','ok'); return jsonify({'status':'playing'})
@app.post('/volume')
def volume():
 e=auth()
 if e:return e
 v=(request.get_json(silent=True) or {}).get('volume')
 if not isinstance(v,(int,float)) or isinstance(v,bool) or not 0<=float(v)<=1:return jsonify({'error':'Informe volume entre 0.0 e 1.0'}),400
 v=float(v); pygame.mixer.music.set_volume(v); SETTINGS['volume']=v; save_settings(); add_history('volume','ok',f'volume={v:.2f}'); return jsonify({'status':'ok','volume':v})
@app.post('/maintenance')
def maintenance():
 e=auth()
 if e:return e
 enabled=(request.get_json(silent=True) or {}).get('enabled')
 if not isinstance(enabled,bool):return jsonify({'error':'Informe enabled true/false'}),400
 SETTINGS['maintenance']=enabled; save_settings(); add_history('maintenance','ok',f'enabled={enabled}'); return jsonify({'maintenance':enabled})
@app.get('/config')
def config():
 e=auth()
 if e:return e
 return jsonify({'allowed_ips':SETTINGS.get('allowed_ips',[]),'schedules':SETTINGS.get('schedules',[])})
@app.post('/config/allowed-ips')
def allowed_ips():
 e=auth()
 if e:return e
 ips=(request.get_json(silent=True) or {}).get('allowed_ips')
 if not isinstance(ips,list) or not all(isinstance(x,str) for x in ips):return jsonify({'error':'allowed_ips deve ser uma lista'}),400
 SETTINGS['allowed_ips']=ips; save_settings(); add_history('allowed_ips','ok',str(ips)); return jsonify({'allowed_ips':ips})
@app.post('/config/sounds')
def config_sounds():
 global SOUNDS
 e=auth()
 if e:return e
 data=request.get_json(silent=True) or {}; name=data.get('name'); path=data.get('path'); remove=data.get('remove',False)
 if not isinstance(name,str) or not name.strip():return jsonify({'error':'Nome invalido'}),400
 if remove:SOUNDS.pop(name,None)
 elif not isinstance(path,str) or not path.strip():return jsonify({'error':'Caminho invalido'}),400
 else:SOUNDS[name]=path
 save_json(SOUNDS_FILE,SOUNDS); add_history('config_sound','ok',f'name={name} remove={remove}'); return jsonify({'sounds':list(SOUNDS.keys())})
@app.post('/config/schedules')
def schedules():
 e=auth()
 if e:return e
 s=(request.get_json(silent=True) or {}).get('schedules')
 if not isinstance(s,list):return jsonify({'error':'schedules deve ser uma lista'}),400
 SETTINGS['schedules']=s; save_settings(); add_history('schedules','ok',f'count={len(s)}'); return jsonify({'schedules':s})

def scheduler():
 fired=set()
 while True:
  now=datetime.now(); key=now.strftime('%Y-%m-%d %H:%M')
  for i,s in enumerate(SETTINGS.get('schedules',[])):
   try:
    if not s.get('enabled',True):continue
    if s.get('time')!=now.strftime('%H:%M'):continue
    days=s.get('weekdays',[])
    if days and now.weekday() not in days:continue
    marker=f'{key}:{i}'
    if marker in fired:continue
    if not SETTINGS.get('maintenance'):play_sound(s.get('sound')); app.logger.info('scheduled sound=%s',s.get('sound'))
    fired.add(marker)
   except Exception as exc:app.logger.error('scheduler error=%s',exc)
  fired={x for x in fired if x.startswith(now.strftime('%Y-%m-%d'))}; time.sleep(10)
threading.Thread(target=scheduler,daemon=True).start()

if __name__=='__main__':app.run(host='0.0.0.0',port=8765,threaded=True)
