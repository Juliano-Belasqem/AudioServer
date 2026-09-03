from flask import Flask, request, jsonify, render_template, Response
import json, logging, os, shutil, subprocess, threading, time, heapq, sys
from collections import defaultdict, deque
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
import pygame
from pycaw.pycaw import AudioUtilities
import comtypes
from diagnostics import bp as diagnostics_bp
from network_service import start_mdns
from music_provider import get_provider, provider_catalog

PROJECT_DIR=os.path.dirname(os.path.abspath(__file__))
SOUNDS_DIR=r'C:\Sounds'; SUPPORTED_EXTENSIONS={'.mp3','.wav','.ogg','.flac'}
SETTINGS_FILE=os.path.join(PROJECT_DIR,'local_settings.json'); BACKUP_DIR=os.path.join(PROJECT_DIR,'backups')
LOG_DIR=os.path.join(PROJECT_DIR,'logs'); LOG_FILE=os.path.join(LOG_DIR,'audio_server.log')
PLAYER_SCRIPT=os.path.join(PROJECT_DIR,'device_player.py')
app=Flask(__name__); app.register_blueprint(diagnostics_bp); pygame.mixer.init(); START_TIME=time.time()
lock=threading.RLock(); history=deque(maxlen=250); request_times=defaultdict(deque); current_sound=None; current_priority='normal'
duck_lock=threading.Lock(); spotify_original_volumes={}; duck_active=False
queue_lock=threading.Condition(); playback_queue=[]; queue_seq=0; current_item=None; stop_worker=False
player_lock=threading.RLock(); active_players=[]
PRIORITIES={'low':10,'normal':20,'high':30,'critical':40}

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
 try:origin=request.remote_addr
 except RuntimeError:origin='scheduler'
 item={'time':datetime.now().isoformat(timespec='seconds'),'ip':origin or 'scheduler','action':action,'result':result,'details':details}
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
 priority=p.get('priority','normal'); priority=priority if priority in PRIORITIES else 'normal'
 return {'volume':float(p.get('volume',SETTINGS.get('volume',1.0))),'duck_enabled':bool(p.get('duck_enabled',SETTINGS.get('ducking',{}).get('enabled',True))),'duck_volume':float(p.get('duck_volume',SETTINGS.get('ducking',{}).get('duck_volume',0.2))),'alert_fade_in_ms':int(p.get('alert_fade_in_ms',300)),'alert_fade_out_ms':int(p.get('alert_fade_out_ms',400)),'favorite':bool(p.get('favorite',False)),'priority':priority}
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
def restore_spotify_volume():
 global duck_active
 cfg=SETTINGS.get('ducking',{}); time.sleep(max(0,int(cfg.get('restore_delay_ms',200)))/1000); comtypes.CoInitialize()
 try:
  with duck_lock:
   current={}
   for s in AudioUtilities.GetAllSessions():
    try:
     if s.Process and s.Process.name().lower()=='spotify.exe':current[s.Process.pid]=s.SimpleAudioVolume
    except Exception:pass
   for pid,orig in list(spotify_original_volumes.items()):
    if pid in current:fade_volume(current[pid],float(current[pid].GetMasterVolume()),float(orig),int(cfg.get('fade_up_ms',2000)))
   spotify_original_volumes.clear(); duck_active=False
 finally:comtypes.CoUninitialize()
def alert_outputs():
 raw=SETTINGS.get('alert_outputs')
 if not isinstance(raw,list) or not raw:return [{'device':'','volume':1.0}]
 out=[]
 for x in raw:
  if not isinstance(x,dict):continue
  out.append({'device':str(x.get('device') or '').strip(),'volume':max(0.0,min(1.0,float(x.get('volume',1.0))))})
 return out or [{'device':'','volume':1.0}]
def players_busy():
 with player_lock:return any(p.poll() is None for p in active_players)
def send_player_command(cmd):
 with player_lock:
  for p in list(active_players):
   if p.poll() is not None:continue
   try:p.stdin.write(cmd+'\n');p.stdin.flush()
   except Exception:pass
def stop_players():
 send_player_command('stop');time.sleep(.08)
 with player_lock:
  for p in list(active_players):
   if p.poll() is None:
    try:p.terminate()
    except Exception:pass
def launch_players(path,profile):
 procs=[]; creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)
 for output in alert_outputs():
  effective=max(0.0,min(1.0,float(profile['volume'])*float(output['volume'])))
  cmd=[sys.executable,PLAYER_SCRIPT,'--file',path,'--volume',str(effective),'--fade-in-ms',str(profile['alert_fade_in_ms'])]
  if output['device']:cmd.extend(['--device',output['device']])
  p=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,creationflags=creationflags)
  procs.append(p)
 with player_lock:
  active_players.clear();active_players.extend(procs)
 return procs
def play_item(item):
 global current_sound,current_priority,current_item
 sounds=scan_sounds(); name=item['sound']
 if name not in sounds:return False,'Audio nao encontrado'
 profile=sound_profile(name); path=sounds[name]['path']; current_sound=name; current_priority=profile['priority']; current_item=item
 try:
  apply_spotify_duck(profile);procs=launch_players(path,profile)
  while any(p.poll() is None for p in procs):time.sleep(.08)
  errors=[]
  for p in procs:
   if p.returncode not in (0,None):
    try:errors.append((p.stderr.read() or '').strip())
    except Exception:errors.append(f'processo retornou {p.returncode}')
  restore_spotify_volume()
  if errors:return False,' | '.join(x for x in errors if x) or 'Falha em uma saída de áudio'
  return True,None
 except Exception as exc:
  stop_players()
  try:restore_spotify_volume()
  except Exception:pass
  return False,str(exc)
 finally:
  with player_lock:active_players.clear()
  current_sound=None; current_priority='normal'; current_item=None
def enqueue_sound(name,source='manual',scheduled_for=None):
 global queue_seq
 if name not in scan_sounds():return False,'Audio nao encontrado',None
 profile=sound_profile(name); item={'id':None,'sound':name,'source':source,'priority':profile['priority'],'queued_at':datetime.now().isoformat(timespec='seconds'),'scheduled_for':scheduled_for}
 with queue_lock:
  queue_seq+=1; item['id']=queue_seq
  heapq.heappush(playback_queue,(-PRIORITIES[item['priority']],queue_seq,item))
  if item['priority']=='critical' and players_busy():stop_players()
  queue_lock.notify()
 return True,None,item
def queue_worker():
 while not stop_worker:
  with queue_lock:
   while not playback_queue and not stop_worker:queue_lock.wait(timeout=1)
   if stop_worker:return
   _,_,item=heapq.heappop(playback_queue)
  ok,err=play_item(item); add_history('queue_play','ok' if ok else 'error',f"sound={item['sound']} priority={item['priority']} source={item['source']} error={err or ''}",item.get('scheduled_for'))
def queue_snapshot():
 with queue_lock:
  ordered=sorted(playback_queue)
  return [dict(x[2]) for x in ordered]
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
def default_environments():
 return {'Normal':{'volume':1.0,'maintenance':False,'ducking':{'enabled':True,'duck_volume':.2,'fade_down_ms':1200,'restore_delay_ms':200,'fade_up_ms':2000}},'Baixo volume':{'volume':.6,'maintenance':False,'ducking':{'enabled':True,'duck_volume':.15,'fade_down_ms':1500,'restore_delay_ms':300,'fade_up_ms':2200}},'Evento':{'volume':1.0,'maintenance':False,'ducking':{'enabled':True,'duck_volume':.1,'fade_down_ms':900,'restore_delay_ms':150,'fade_up_ms':1600}},'Manutencao':{'volume':.5,'maintenance':True,'ducking':{'enabled':False,'duck_volume':.2,'fade_down_ms':1200,'restore_delay_ms':200,'fade_up_ms':2000}}}
def apply_environment(name):
 env=SETTINGS.get('environment_profiles',{}).get(name)
 if not env:return False
 SETTINGS['volume']=float(env.get('volume',SETTINGS.get('volume',1))); SETTINGS['maintenance']=bool(env.get('maintenance',False)); SETTINGS['ducking'].update(env.get('ducking',{})); SETTINGS['active_environment']=name; save_settings(); return True

setup_logging(); SETTINGS=load_json(SETTINGS_FILE,{'volume':1.0,'maintenance':False,'allowed_ips':[],'schedules':[],'ducking':{'enabled':True,'duck_volume':.2,'fade_down_ms':1200,'restore_delay_ms':200,'fade_up_ms':2000},'sound_profiles':{},'environment_profiles':default_environments(),'active_environment':'Normal','alert_outputs':[{'device':'','volume':1.0}],'music':{'provider':'spotify'}});SETTINGS.setdefault('sound_profiles',{});SETTINGS.setdefault('schedules',[]);SETTINGS.setdefault('ducking',{});SETTINGS.setdefault('environment_profiles',default_environments());SETTINGS.setdefault('active_environment','Normal');SETTINGS.setdefault('alert_outputs',[{'device':'','volume':1.0}]);SETTINGS.setdefault('music',{'provider':'spotify'})
for k,v in {'enabled':True,'duck_volume':.2,'fade_down_ms':1200,'restore_delay_ms':200,'fade_up_ms':2000}.items():SETTINGS['ducking'].setdefault(k,v)
threading.Thread(target=queue_worker,daemon=True).start()
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
 cfg=SETTINGS['ducking'];sp=spotify_state();q=queue_snapshot()
 return jsonify({'status':'online','server_time':datetime.now().isoformat(timespec='seconds'),'friendly_url':'http://audioserver.local:8765/','version':version(),'uptime_seconds':int(time.time()-START_TIME),'playing':players_busy(),'current_sound':current_sound,'current_priority':current_priority,'queue_length':len(q),'volume':round(float(SETTINGS.get('volume',1.0)),2),'sounds_count':len(scan_sounds()),'maintenance':bool(SETTINGS.get('maintenance')),'active_environment':SETTINGS.get('active_environment'),'alert_outputs':alert_outputs(),'next_schedule':next_schedule(),'spotify':sp,'ducking':{'enabled':cfg['enabled'],'active':duck_active,'spotify_volume_during_alert':cfg['duck_volume'],'fade_down_ms':cfg['fade_down_ms'],'fade_up_ms':cfg['fade_up_ms'],'restore_delay_ms':cfg['restore_delay_ms']}})
@app.get('/music/status')
def music_status():
 pid=SETTINGS.get('music',{}).get('provider','spotify'); p=get_provider(pid); data=p.status();data['providers']=provider_catalog();return jsonify(data)
@app.post('/music/command')
def music_command():
 data=request.get_json(silent=True) or {};cmd=str(data.get('command') or '');p=get_provider(SETTINGS.get('music',{}).get('provider','spotify'))
 if cmd=='volume':ok,err=p.set_volume(data.get('value',1.0)) if hasattr(p,'set_volume') else (False,'Volume não suportado')
 else:ok,err=p.command(cmd)
 add_history('music_command','ok' if ok else 'error',f'provider={p.id} command={cmd} error={err or ""}')
 if not ok:return jsonify({'error':err}),409
 return jsonify({'status':'ok',**p.status()})
@app.post('/music/provider')
def music_provider_select():
 pid=str((request.get_json(silent=True) or {}).get('provider') or '')
 available={x['id']:x for x in provider_catalog()}
 if pid not in available:return jsonify({'error':'Provedor desconhecido'}),400
 if not available[pid]['implemented']:return jsonify({'error':'Esse provedor ainda não foi implementado.'}),409
 SETTINGS.setdefault('music',{})['provider']=pid;save_settings();add_history('music_provider','ok',pid);return jsonify({'provider':pid})
@app.get('/sounds')
def sounds():
 data=scan_sounds();return jsonify({'directory':SOUNDS_DIR,'sounds':[{'name':n,**meta,'profile':sound_profile(n)} for n,meta in data.items()]})
@app.get('/history')
def get_history():return jsonify({'history':list(history)})
@app.get('/queue')
def get_queue():return jsonify({'current':current_item,'queue':queue_snapshot()})
@app.post('/queue/clear')
def clear_queue():
 with queue_lock:playback_queue.clear()
 add_history('queue_clear','ok');return jsonify({'status':'cleared'})
@app.post('/queue/remove')
def remove_queue():
 target=(request.get_json(silent=True) or {}).get('id'); removed=False
 with queue_lock:
  keep=[]
  for entry in playback_queue:
   if entry[2]['id']==target:removed=True
   else:keep.append(entry)
  playback_queue[:]=keep;heapq.heapify(playback_queue)
 return jsonify({'removed':removed})
@app.post('/play')
def play():
 if SETTINGS.get('maintenance'):return jsonify({'error':'Servidor em modo de manutencao'}),503
 name=(request.get_json(silent=True) or {}).get('sound');ok,err,item=enqueue_sound(name,'manual')
 if not ok:add_history('play','error',f'sound={name} error={err}');return jsonify({'error':err}),404
 add_history('enqueue','ok',f"sound={name} priority={item['priority']}");return jsonify({'status':'queued','sound':name,'priority':item['priority'],'id':item['id']})
@app.post('/stop')
def stop():stop_players();add_history('stop','ok');return jsonify({'status':'stopped'})
@app.post('/pause')
def pause():send_player_command('pause');add_history('pause','ok');return jsonify({'status':'paused'})
@app.post('/resume')
def resume():send_player_command('resume');add_history('resume','ok');return jsonify({'status':'playing'})
@app.post('/volume')
def volume():
 v=(request.get_json(silent=True) or {}).get('volume')
 if not isinstance(v,(int,float)) or isinstance(v,bool) or not 0<=float(v)<=1:return jsonify({'error':'Volume invalido'}),400
 SETTINGS['volume']=float(v);save_settings();return jsonify({'volume':float(v)})
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
def config():return jsonify({'allowed_ips':SETTINGS.get('allowed_ips',[]),'schedules':SETTINGS.get('schedules',[]),'sound_profiles':SETTINGS.get('sound_profiles',{}),'ducking':SETTINGS['ducking'],'environment_profiles':SETTINGS.get('environment_profiles',{}),'active_environment':SETTINGS.get('active_environment'),'alert_outputs':alert_outputs(),'music':SETTINGS.get('music',{})})
@app.post('/config/alert-outputs')
def configure_alert_outputs():
 if players_busy():return jsonify({'error':'Pare o alerta atual antes de alterar as saídas.'}),409
 data=request.get_json(silent=True) or {};outputs=data.get('outputs')
 if not isinstance(outputs,list) or not outputs:return jsonify({'error':'Selecione pelo menos uma saída.'}),400
 clean=[];seen=set()
 for x in outputs:
  if not isinstance(x,dict):continue
  device=str(x.get('device') or '').strip(); volume=x.get('volume',1.0)
  try:volume=max(0.0,min(1.0,float(volume)))
  except Exception:return jsonify({'error':'Volume de saída inválido.'}),400
  key=device.lower()
  if key in seen:continue
  seen.add(key);clean.append({'device':device,'volume':volume})
 if not clean:return jsonify({'error':'Selecione pelo menos uma saída válida.'}),400
 SETTINGS['alert_outputs']=clean;save_settings();add_history('alert_outputs','ok',f'count={len(clean)}');return jsonify({'outputs':clean})
@app.get('/config/export')
def export_config():
 payload=json.dumps(SETTINGS,ensure_ascii=False,indent=2);return Response(payload,mimetype='application/json',headers={'Content-Disposition':'attachment; filename=audioserver_config.json'})
@app.post('/config/import')
def import_config():
 global SETTINGS
 data=request.get_json(silent=True)
 if not isinstance(data,dict):return jsonify({'error':'JSON de configuracao invalido'}),400
 required={'ducking','schedules','sound_profiles'}
 if not required.issubset(set(data.keys())):return jsonify({'error':'Arquivo nao parece ser uma configuracao do AudioServer'}),400
 backup_settings();SETTINGS=data;SETTINGS.setdefault('environment_profiles',default_environments());SETTINGS.setdefault('active_environment','Normal');SETTINGS.setdefault('alert_outputs',[{'device':'','volume':1.0}]);SETTINGS.setdefault('music',{'provider':'spotify'});save_settings();add_history('config_import','ok');return jsonify({'status':'imported'})
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
 if 'priority' in data and data['priority'] in PRIORITIES:p['priority']=data['priority']
 save_settings();return jsonify({'sound':name,'profile':sound_profile(name)})
@app.post('/environments/apply')
def environments_apply():
 name=(request.get_json(silent=True) or {}).get('name')
 if not apply_environment(name):return jsonify({'error':'Perfil nao encontrado'}),404
 add_history('environment_apply','ok',name);return jsonify({'active_environment':name})
@app.post('/environments/save')
def environments_save():
 data=request.get_json(silent=True) or {};name=(data.get('name') or '').strip()
 if not name:return jsonify({'error':'Nome obrigatorio'}),400
 SETTINGS.setdefault('environment_profiles',{})[name]={'volume':SETTINGS.get('volume',1.0),'maintenance':SETTINGS.get('maintenance',False),'ducking':dict(SETTINGS.get('ducking',{}))};SETTINGS['active_environment']=name;save_settings();return jsonify({'environment_profiles':SETTINGS['environment_profiles'],'active_environment':name})
@app.post('/environments/delete')
def environments_delete():
 name=(request.get_json(silent=True) or {}).get('name')
 if name in ('Normal','Baixo volume','Evento','Manutencao'):return jsonify({'error':'Perfil padrao nao pode ser removido'}),400
 SETTINGS.setdefault('environment_profiles',{}).pop(name,None);save_settings();return jsonify({'environment_profiles':SETTINGS['environment_profiles']})
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
     ok,err,item=enqueue_sound(s.get('sound'),'schedule',key);add_history('schedule_enqueue','ok' if ok else 'error',f"sound={s.get('sound')} error={err or ''}",key)
    fired.add(marker)
   except Exception as exc:app.logger.error('scheduler error=%s',exc)
  fired={x for x in fired if x.startswith(now.strftime('%Y-%m-%d'))};time.sleep(10)
threading.Thread(target=scheduler,daemon=True).start()
if __name__=='__main__':
 start_mdns(8765)
 app.run(host='0.0.0.0',port=8765,threaded=True)