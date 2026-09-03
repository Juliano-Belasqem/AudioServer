import json, os, shutil, socket, subprocess, sys, threading, time, urllib.request
from collections import deque
from datetime import datetime

import psutil
import pygame
from flask import Blueprint, jsonify, render_template, request
from pycaw.pycaw import AudioUtilities
import comtypes

try:
 from pygame._sdl2 import audio as sdl2_audio
except Exception:
 sdl2_audio=None

PROJECT_DIR=os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE=os.path.join(PROJECT_DIR,'local_settings.json')
SOUNDS_DIR=r'C:\Sounds'
PLAYER_SCRIPT=os.path.join(PROJECT_DIR,'device_player.py')
SUPPORTED_EXTENSIONS={'.mp3','.wav','.ogg','.flac'}
alerts=deque(maxlen=100)
_last_health={}
_audio_lock=threading.RLock()
_output_test_status={}

bp=Blueprint('diagnostics',__name__)

def load_settings():
 try:
  with open(SETTINGS_FILE,'r',encoding='utf-8') as f:return json.load(f)
 except Exception:return {}

def save_settings(settings):
 with open(SETTINGS_FILE,'w',encoding='utf-8') as f:json.dump(settings,f,ensure_ascii=False,indent=2)

def audio_devices():
 try:
  if sdl2_audio is None:return []
  return [str(x) for x in sdl2_audio.get_audio_device_names(False)]
 except Exception:return []

def selected_audio_device():
 return (load_settings().get('audio_device') or '').strip()

def configured_outputs():
 settings=load_settings(); raw=settings.get('alert_outputs',[])
 if not isinstance(raw,list):raw=[]
 result=[]
 for x in raw:
  if not isinstance(x,dict):continue
  device=str(x.get('device') or '').strip()
  try:volume=max(0.0,min(1.0,float(x.get('volume',1.0))))
  except Exception:volume=1.0
  try:delay=max(0,min(5000,int(x.get('delay_ms',0))))
  except Exception:delay=0
  result.append({'device':device,'volume':volume,'delay_ms':delay})
 return result

def output_status():
 detected=audio_devices(); detected_lower={x.lower() for x in detected}
 rows=[]
 for x in configured_outputs():
  device=x['device']; available=(not device) or device.lower() in detected_lower
  test=_output_test_status.get(device.lower(),{})
  rows.append({**x,'display_name':device or 'Padrão do Windows','available':available,'last_test':test.get('time'),'last_test_ok':test.get('ok'),'last_error':test.get('error')})
 return rows

def initialize_audio_device(device=None,persist=False):
 settings=load_settings(); wanted=(device if device is not None else settings.get('audio_device','')) or ''
 wanted=str(wanted).strip()
 with _audio_lock:
  if pygame.mixer.get_init() and pygame.mixer.music.get_busy():return False,'Existe um alerta em reprodução. Pare o áudio antes de trocar a saída.'
  previous_volume=float(settings.get('volume',1.0))
  try:
   if pygame.mixer.get_init():pygame.mixer.quit()
   if wanted:pygame.mixer.init(devicename=wanted)
   else:pygame.mixer.init()
   pygame.mixer.music.set_volume(max(0.0,min(1.0,previous_volume)))
  except Exception as exc:
   try:
    if pygame.mixer.get_init():pygame.mixer.quit()
    pygame.mixer.init(); pygame.mixer.music.set_volume(max(0.0,min(1.0,previous_volume)))
   except Exception:pass
   return False,str(exc)
  if persist:
   settings['audio_device']=wanted;save_settings(settings)
  return True,None

def spotify_info():
 found=False; vols=[];comtypes.CoInitialize()
 try:
  for s in AudioUtilities.GetAllSessions():
   try:
    if s.Process and s.Process.name().lower()=='spotify.exe':found=True;vols.append(float(s.SimpleAudioVolume.GetMasterVolume()))
   except Exception:pass
 finally:comtypes.CoUninitialize()
 return {'running':found,'volume':round(max(vols),2) if vols else None,'sessions':len(vols)}

def scan_sound_names():
 result=[]
 if not os.path.isdir(SOUNDS_DIR):return result
 for root,_,names in os.walk(SOUNDS_DIR):
  for name in names:
   if os.path.splitext(name)[1].lower() in SUPPORTED_EXTENSIONS:
    path=os.path.join(root,name);rel=os.path.relpath(path,SOUNDS_DIR).replace('\\','/')
    result.append({'name':os.path.splitext(name)[0],'relative_path':rel,'path':path})
 return sorted(result,key=lambda x:x['relative_path'].lower())

def find_test_sound(relative_path=None):
 sounds=scan_sound_names()
 if not sounds:return None
 if relative_path:
  wanted=str(relative_path).replace('\\','/').lower()
  for x in sounds:
   if x['relative_path'].lower()==wanted:return x['path']
 return sounds[0]['path']

def health_snapshot():
 usage=shutil.disk_usage(PROJECT_DIR);sounds_ok=os.path.isdir(SOUNDS_DIR) and os.access(SOUNDS_DIR,os.R_OK)
 try:mixer_ok=bool(pygame.mixer.get_init())
 except Exception:mixer_ok=False
 sp=spotify_info();devices=audio_devices();selected=selected_audio_device()
 return {'time':datetime.now().isoformat(timespec='seconds'),'hostname':socket.gethostname(),'friendly_name':'audioserver.local','sounds_directory':SOUNDS_DIR,'sounds_directory_ok':sounds_ok,'audio_mixer_ok':mixer_ok,'audio_device':selected or 'Padrão do Windows','audio_devices':devices,'alert_outputs':output_status(),'spotify':sp,'disk_free_gb':round(usage.free/(1024**3),2),'disk_total_gb':round(usage.total/(1024**3),2),'cpu_percent':psutil.cpu_percent(interval=.1),'memory_percent':psutil.virtual_memory().percent}

def emit_alert(kind,message,severity='warning'):
 item={'time':datetime.now().isoformat(timespec='seconds'),'kind':kind,'message':message,'severity':severity};alerts.appendleft(item)
 settings=load_settings();cfg=settings.get('failure_alerts',{});url=(cfg.get('webhook_url') or '').strip()
 if cfg.get('enabled') and url:
  def send():
   try:
    body=json.dumps({'source':'AudioServer',**item}).encode('utf-8');req=urllib.request.Request(url,data=body,headers={'Content-Type':'application/json'},method='POST');urllib.request.urlopen(req,timeout=5).read()
   except Exception:pass
  threading.Thread(target=send,daemon=True).start()

def monitor_loop():
 global _last_health
 while True:
  try:
   h=health_snapshot();checks={'sounds_directory':(h['sounds_directory_ok'],'Pasta C:\\Sounds indisponível'),'audio_mixer':(h['audio_mixer_ok'],'Mixer de áudio não está disponível'),'spotify':(h['spotify']['running'],'Spotify não foi encontrado'),'disk_space':(h['disk_free_gb']>=5,f"Pouco espaço em disco: {h['disk_free_gb']} GB livres")}
   unavailable=[x['display_name'] for x in h['alert_outputs'] if not x['available']]
   checks['alert_outputs']=(not unavailable,'Saídas de alerta indisponíveis: '+', '.join(unavailable))
   for key,(ok,msg) in checks.items():
    previous=_last_health.get(key,True)
    if previous and not ok:emit_alert(key,msg,'error')
    elif not previous and ok:emit_alert(key,f'{key} normalizado','info')
    _last_health[key]=ok
  except Exception:pass
  time.sleep(60)

@bp.get('/diagnostics')
def diagnostics_page():return render_template('diagnostics.html')

@bp.get('/api/diagnostics')
def diagnostics_api():
 h=health_snapshot();h['alerts']=list(alerts);h['failure_alerts']=load_settings().get('failure_alerts',{'enabled':False,'webhook_url':''});return jsonify(h)

@bp.get('/api/audio-devices')
def audio_devices_api():
 devices=audio_devices();selected=selected_audio_device();return jsonify({'devices':devices,'selected':selected,'display_selected':selected or 'Padrão do Windows','mixer_ready':bool(pygame.mixer.get_init()),'outputs':output_status(),'test_sounds':[{k:v for k,v in x.items() if k!='path'} for x in scan_sound_names()]})

@bp.post('/config/audio-device')
def configure_audio_device():
 data=request.get_json(silent=True) or {};device=str(data.get('device') or '').strip();devices=audio_devices()
 if device and devices and device not in devices:return jsonify({'error':'Dispositivo não encontrado. Atualize a lista e tente novamente.'}),400
 ok,err=initialize_audio_device(device,persist=True)
 if not ok:return jsonify({'error':f'Não foi possível ativar a saída: {err}'}),409
 return jsonify({'status':'ok','selected':device,'display_selected':device or 'Padrão do Windows'})

@bp.post('/config/alert-outputs-advanced')
def configure_alert_outputs_advanced():
 data=request.get_json(silent=True) or {};outputs=data.get('outputs')
 if not isinstance(outputs,list) or not outputs:return jsonify({'error':'Selecione pelo menos uma saída.'}),400
 clean=[];seen=set()
 for x in outputs:
  if not isinstance(x,dict):continue
  device=str(x.get('device') or '').strip();key=device.lower()
  if key in seen:continue
  try:volume=max(0.0,min(1.0,float(x.get('volume',1.0))));delay=max(0,min(5000,int(x.get('delay_ms',0))))
  except Exception:return jsonify({'error':'Volume ou atraso inválido.'}),400
  seen.add(key);clean.append({'device':device,'volume':volume,'delay_ms':delay})
 if not clean:return jsonify({'error':'Nenhuma saída válida.'}),400
 settings=load_settings();settings['alert_outputs']=clean;save_settings(settings);return jsonify({'outputs':clean})

@bp.post('/audio-output/test')
def test_output():
 data=request.get_json(silent=True) or {};device=str(data.get('device') or '').strip();relative_path=data.get('relative_path');volume=max(0.0,min(1.0,float(data.get('volume',1.0))));delay=max(0,min(5000,int(data.get('delay_ms',0))))
 detected=audio_devices()
 if device and device not in detected:return jsonify({'error':'Essa saída não está disponível no momento.'}),409
 path=find_test_sound(relative_path)
 if not path:return jsonify({'error':'Nenhum áudio disponível em C:\\Sounds para teste.'}),404
 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0);cmd=[sys.executable,PLAYER_SCRIPT,'--file',path,'--volume',str(volume),'--fade-in-ms','100','--delay-ms',str(delay)]
 if device:cmd.extend(['--device',device])
 try:
  result=subprocess.run(cmd,capture_output=True,text=True,timeout=30,creationflags=creationflags);ok=result.returncode==0;err=(result.stderr or '').strip() if not ok else None
 except Exception as exc:ok=False;err=str(exc)
 _output_test_status[device.lower()]={'time':datetime.now().isoformat(timespec='seconds'),'ok':ok,'error':err}
 if not ok:return jsonify({'error':err or 'Falha no teste da saída.'}),500
 return jsonify({'status':'ok','device':device or 'Padrão do Windows'})

@bp.post('/config/failure-alerts')
def configure_alerts():
 data=request.get_json(silent=True) or {};settings=load_settings();cfg=settings.setdefault('failure_alerts',{})
 if 'enabled' in data:cfg['enabled']=bool(data['enabled'])
 if 'webhook_url' in data:cfg['webhook_url']=str(data['webhook_url']).strip()
 save_settings(settings);return jsonify({'failure_alerts':cfg})

@bp.post('/diagnostics/test-alert')
def test_alert():emit_alert('test','Alerta de teste do AudioServer','info');return jsonify({'status':'sent'})

try:initialize_audio_device(selected_audio_device(),persist=False)
except Exception:pass
threading.Thread(target=monitor_loop,daemon=True).start()
