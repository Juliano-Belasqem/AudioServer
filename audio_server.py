from flask import Flask, request, jsonify, render_template
import json, logging, os, shutil, subprocess, threading, time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
import pygame
from pycaw.pycaw import AudioUtilities
import comtypes
from diagnostics import bp as diagnostics_bp
from network_service import start_mdns

PROJECT_DIR=os.path.dirname(os.path.abspath(__file__))
SOUNDS_DIR=r'C:\Sounds'; SUPPORTED_EXTENSIONS={'.mp3','.wav','.ogg','.flac'}
SETTINGS_FILE=os.path.join(PROJECT_DIR,'local_settings.json'); BACKUP_DIR=os.path.join(PROJECT_DIR,'backups')
LOG_DIR=os.path.join(PROJECT_DIR,'logs'); LOG_FILE=os.path.join(LOG_DIR,'audio_server.log')
app=Flask(__name__); app.register_blueprint(diagnostics_bp); pygame.mixer.init(); START_TIME=time.time(); lock=threading.Lock(); history=deque(maxlen=250); request_times=defaultdict(deque); current_sound=None
duck_lock=threading.Lock(); duck_generation=0; spotify_original_volumes={}; duck_active=False

def setup_logging():
 os.makedirs(LOG_DIR,exist_ok=True); h=RotatingFileHandler(LOG_FILE,maxBytes=2*1024*1024,backupCount=5,encoding='utf-8'); h.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')); app.logger.setLevel(logging.INFO); app.logger.addHandler(h)
def load_json(path,default):
 try:
  with open(path,'r',encoding='utf-8') as f:return json.load(f)
 except (FileNotFoundError,json.JSONDecodeError):return default
def backup_settings():
 if not os.path.exists(SETTINGS_FILE):return
 os.makedirs(BACKUP_DIR,exist_ok=True); name='local_settings_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.json'; shutil.copy2(SETTINGS_FILE,os.path.join(BACKUP_DIR,name))
 files=sorted([x for x in os.listdir(BACKUP_DIR) if x.endswith('.json')])
 for old in files[:-20]:
  try:os.remove(os.path.join(BACKUP_DIR,old))
  except OSError:pass
def save_settings():
 backup_settings()
 with open(SETTINGS_FILE,'w',encoding='utf-8') as f:json.dump(SETTINGS,f,ensure_ascii=False,indent=2)
def version():
 try:return subprocess.run(['git','rev-parse','--short','HEAD'],cwd=PROJECT_DIR,capture_output=True,text=True,timeout=3,check=True).stdout.strip()
 except Exception:return 'unknown'
def ip():return request.remote_addr or 'unknown'
def add_history(action,result,details='',scheduled_for=None):
 item={'time':datetime.now().isoformat(timespec='seconds'),'ip':request.remote_addr if request else 'scheduler','action':action,'result':result,'details':details}
 if scheduled_for:item['scheduled_for']=scheduled_for
 history.appendleft(item); app.logger.info('action=%s | result=%s | %s',action,result,details)
def scan_sounds():
 sounds={}; stems={}; files=[]
 if not os.path.isdir(SOUNDS_DIR):return sounds
 for root,_,names in os.walk(SOUNDS_DIR):
  for name in names:
   if os.path.splitext(name)[1].lower() in SUPPORTED_EXTENSIONS:
    path=os.path.join(root,name); rel=os.path.relpath(path,SOUNDS_DIR); files.append((rel,path)); stems.setdefault(os.path.splitext(name)[0],[]).append(rel)
 for rel,path in sorted(files,key=lambda x:x[0].lower()):
  stem=os.path.splitext(os.path.basename(rel))[0]; category=os.path.dirname(rel).replace('\\','/') or 'Geral'; key=stem if len(stems[stem])==1 else os.path.splitext(rel)[0].replace('\\','/')
  sounds[key]={'path':path,'file':os.path.basename(path),'category':category,'relative_path':rel.replace('\\','/')}
 return sounds
def sound_profile(name):
 p=SETTINGS.setdefault('sound_profiles',{}).get(name,{})
 return {'volume':float(p.get('volume',SETTINGS.get('volume',1.0))),'duck_enabled':bool(p.get('duck_enabled',SETTINGS.get('ducking',{}).get('enabled',True))),'duck_volume':float(p.get('duck_volume',SETTINGS.get('ducking',{}).get('duck_volume',0.2))),'alert_fade_in_ms':int(p.get('alert_fade_in_ms',300)),'alert_fade_out_ms':int(p.get('alert_fade_out_ms',400)),'favorite':bool(p.get('favorite',False))}
def spotify_state():
 comtypes.CoInitialize(); found=False; vols=[]
 try:
  for s in AudioUtilities.GetAllSessions():
   try:
    if s.Process and s.Process.name().lower()=='spotify.exe':found=True; vols.append(float(s.SimpleAudioVolume.GetMasterVolume()))
   except Exception:pass
 finally:comtypes.CoUninitialize()
 return {'running':found,'volume':round(max(vols),2) if vols else None,'sessions':len(vols)}
def fade_volume(obj,start,target,duration_ms,steps=24):
 d=max(0,int(duration_ms))/1000
 if d<=0:obj.SetMasterVolume(float(target),None);return
 for i in range(1,steps+1):obj.SetMasterVolume(max(0,min(1,start+(target-start)*(i/steps))),None);time.sleep(d/steps)
def apply_spotify_duck(profile):
 global duck_active
 if not profile['duck_enabled']:return
 cfg=SETTINGS.get('ducking',{}); target=max(0,min(1,profile['duck_volume'])); fade_ms=int(cfg.get('fade_down_ms',1200)); comtypes.CoInitialize()
 try:
  with duck_lock:
   for s in AudioUtilities.GetAllSessions():
    try:
     if not s.Process or s.Process.name().lower()!='spotify.exe':continue
     pid=s.Process.pid; v=s.SimpleAudioVolume; cur=float(v.GetMasterVolume()); spotify_original_volumes.setdefault(pid,cur); fade_volume(v,cur,target,fade_ms)
    except Exception as exc:app.logger.warning('duck error=%s',exc)
   duck_active=bool(spotify_original_volumes)
 finally:comtypes.CoUninitialize()
def restore_spotify_volume(expected_generation=None):
 global duck_active
 cfg=SETTINGS.get('ducking',{}); time.sleep(max(0,int(cfg.get('restore_delay_ms',200)))/1000); comtypes.CoInitialize()
 try:
  with duck_lock:
   if expected_generation is not None and expected_generation!=duck_generation:return
   current={}
   for s in AudioUtilities.GetAllSessions():
    try:
     if s.Process and s.Process.name().lower()=='spotify.exe':current[s.Process.pid]=s.SimpleAudioVolume
    except Exception:pass
   for pid,orig in list(spotify_original_volumes.items()):
    if pid in current:fade_volume(current[pid],float(current[pid].GetMasterVolume()),float(orig),int(cfg.get('fade_up_ms',2000)))
   spotify_original_volumes.clear(); duck_active=False
 finally:comtypes.CoUninitialize()
def wait_and_restore(gen):
 while pygame.mixer.music.get_busy():time.sleep(.1)
 restore_spotify_volume(gen)
def play_sound(name,source='manual'):
 global current_sound,duck_generation
 sounds=scan_sounds()
 if name not in sounds:return False,'Audio nao encontrado'
 profile=sound_profile(name); path=sounds[name]['path']
 with lock:
  apply_spotify_duck(profile); duck_generation+=1; gen=duck_generation; pygame.mixer.music.set_volume(profile['volume']); pygame.mixer.music.load(path); pygame.mixer.music.play(fade_ms=profile['alert_fade_in_ms']); current_sound=name
 threading.Thread(target=wait_and_restore,args=(gen,),daemon=True).start();return True,None
def next_schedule():
 now=datetime.now(); candidates=[]
 for s in SETTINGS.get('schedules',[]):
  if not s.get('enabled',True) or not s.get('time'):continue
  try:h,m=map(int,s['time'].split(':'))
  except Exception:continue
  days=s.get('weekdays',[])
  for off in range(8):
   d=now+timedelta(days=off)
   if days and d.weekday() not in days:continue
   dt=d.replace(hour=h,minute=m,second=0,microsecond=0)
   if dt>now:candidates.append((dt,s));break
 if not candidates:return None
 dt,s=min(candidates,key=lambda x:x[0]);return {'sound':s.get('sound'),'datetime':dt.isoformat(timespec='minutes'),'time':s.get('time'),'weekdays':s.get('weekdays',[])}

setup_logging(); SETTINGS=load_json(SETTINGS_FILE,{'volume':1.0,'maintenance':False,'allowed_ips':[],'schedules':[],'ducking':{'enabled':True,'duck_volume':.2,'fade_down_ms':1200,'restore_delay_ms':200,'fade_up_ms':2000},'sound_profiles':{}});SETTINGS.setdefault('sound_profiles',{});SETTINGS.setdefault('schedules',[]);SETTINGS.setdefault('ducking',{})
for k,v in {'enabled':True,'duck_volume':.2,'fade_down_ms':1200,'restore_delay_ms':200,'fade_up_ms':2000}.items():SETTINGS['ducking'].setdefault(k,v)
pygame.mixer.music.set_volume(float(SETTINGS.get('volume',1.0)))
@app.before_request
def protection():
 allowed=SETTINGS.get('allowed_ips',[])
 if allowed and ip() not in allowed and ip() not in ('127.0.0.1','::1'):return jsonify({'error':'IP nao autorizado'}),403
 q=request_times[ip()];now=time.time()
 while q and now-q[0]>60:q.popleft()
 if len(q)>=120:return jsonify({'error':'Muitas requisicoes'}),429
 q.append(now)
@app.get('/')
def dashboard():return render_template('index.html')
@app.get('/status')
def status():
 busy=bool(pygame.mixer.music.get_busy());sounds=scan_sounds();cfg=SETTINGS['ducking'];sp=spotify_state()
 return jsonify({'status':'online','server_time':datetime.now().isoformat(timespec='seconds'),'friendly_url':'http://audioserver.local:8765/','version':version(),'uptime_seconds':int(time.time()-START_TIME),'playing':busy,'current_sound':current_sound if busy else None,'volume':round(pygame.mixer.music.get_volume(),2),'sounds_count':len(sounds),'maintenance':bool(SETTINGS.get('maintenance')),'next_schedule':next_schedule(),'spotify':sp,'ducking':{'enabled':cfg['enabled'],'active':duck_active,'spotify_volume_during_alert':cfg['duck_volume'],'fade_down_ms':cfg['fade_down_ms'],'fade_up_ms':cfg['fade_up_ms'],'restore_delay_ms':cfg['restore_delay_ms']}})
@app.get('/sounds')
def sounds():
 data=scan_sounds();return jsonify({'directory':SOUNDS_DIR,'sounds':[{'name':n,**meta,'profile':sound_profile(n)} for n,meta in data.items()]})
@app.get('/history')
def get_history():return jsonify({'history':list(history)})
@app.post('/play')
def play():
 if SETTINGS.get('maintenance'):return jsonify({'error':'Servidor em modo de manutencao'}),503
 name=(request.get_json(silent=True) or {}).get('sound');ok,err=play_sound(name)
 if not ok:add_history('play','error',f'sound={name} error={err}');return jsonify({'error':err}),404
 add_history('play','ok',f'sound={name}');return jsonify({'status':'playing','sound':name})
@app.post('/stop')
def stop():
 fade=sound_profile(current_sound)['alert_fade_out_ms'] if current_sound else 400;pygame.mixer.music.fadeout(fade);restore_spotify_volume();add_history('stop','ok');return jsonify({'status':'stopped'})
@app.post('/pause')
def pause():pygame.mixer.music.pause();add_history('pause','ok');return jsonify({'status':'paused'})
@app.post('/resume')
def resume():pygame.mixer.music.unpause();add_history('resume','ok');return jsonify({'status':'playing'})
@app.post('/volume')
def volume():
 v=(request.get_json(silent=True) or {}).get('volume')
 if not isinstance(v,(int,float)) or isinstance(v,bool) or not 0<=float(v)<=1:return jsonify({'error':'Volume invalido'}),400
 SETTINGS['volume']=float(v);pygame.mixer.music.set_volume(float(v));save_settings();return jsonify({'volume':float(v)})
@app.post('/ducking')
def ducking():
 data=request.get_json(silent=True) or {};cfg=SETTINGS['ducking']
 if 'enabled' in data:cfg['enabled']=bool(data['enabled'])
 if 'duck_volume' in data:cfg['duck_volume']=max(0,min(1,float(data['duck_volume'])))
 for f in ('fade_down_ms','fade_up_ms','restore_delay_ms'):
  if f in data:cfg[f]=max(0,min(10000,int(data[f])))
 save_settings();return jsonify({'ducking':cfg})
@app.post('/maintenance')
def maintenance():SETTINGS['maintenance']=bool((request.get_json(silent=True) or {}).get('enabled'));save_settings();return jsonify({'maintenance':SETTINGS['maintenance']})
@app.get('/config')
def config():return jsonify({'allowed_ips':SETTINGS.get('allowed_ips',[]),'schedules':SETTINGS.get('schedules',[]),'sound_profiles':SETTINGS.get('sound_profiles',{}),'ducking':SETTINGS['ducking']})
@app.post('/config/schedules')
def schedules():
 s=(request.get_json(silent=True) or {}).get('schedules')
 if not isinstance(s,list):return jsonify({'error':'schedules deve ser uma lista'}),400
 SETTINGS['schedules']=s;save_settings();add_history('schedules','ok',f'count={len(s)}');return jsonify({'schedules':s})
@app.post('/config/sound-profile')
def sound_profile_api():
 data=request.get_json(silent=True) or {};name=data.get('sound')
 if name not in scan_sounds():return jsonify({'error':'Audio nao encontrado'}),404
 p=SETTINGS.setdefault('sound_profiles',{}).setdefault(name,{})
 for f in ('volume','duck_volume'):
  if f in data:p[f]=max(0,min(1,float(data[f])))
 for f in ('alert_fade_in_ms','alert_fade_out_ms'):
  if f in data:p[f]=max(0,min(10000,int(data[f])))
 for f in ('duck_enabled','favorite'):
  if f in data:p[f]=bool(data[f])
 save_settings();return jsonify({'sound':name,'profile':sound_profile(name)})
def scheduler():
 fired=set()
 while True:
  now=datetime.now();key=now.strftime('%Y-%m-%d %H:%M')
  for i,s in enumerate(list(SETTINGS.get('schedules',[]))):
   try:
    if not s.get('enabled',True) or s.get('time')!=now.strftime('%H:%M'):continue
    days=s.get('weekdays',[])
    if days and now.weekday() not in days:continue
    marker=f'{key}:{i}'
    if marker in fired:continue
    if not SETTINGS.get('maintenance'):
     ok,err=play_sound(s.get('sound'),'schedule');add_history('schedule_play','ok' if ok else 'error',f"sound={s.get('sound')} error={err or ''}",scheduled_for=key)
    fired.add(marker)
   except Exception as exc:app.logger.error('scheduler error=%s',exc)
  fired={x for x in fired if x.startswith(now.strftime('%Y-%m-%d'))};time.sleep(10)
threading.Thread(target=scheduler,daemon=True).start()
if __name__=='__main__':
 start_mdns(8765)
 app.run(host='0.0.0.0',port=8765,threaded=True)
