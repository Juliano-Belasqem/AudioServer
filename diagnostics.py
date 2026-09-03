import json, os, shutil, socket, threading, time, urllib.request
from collections import deque
from datetime import datetime

import psutil
import pygame
from flask import Blueprint, jsonify, render_template, request
from pycaw.pycaw import AudioUtilities
import comtypes
from audit_store import tail_loop as audit_tail_loop, recent_events as audit_recent_events, metrics as audit_metrics, database_info as audit_database_info

try:
 from pygame._sdl2 import audio as sdl2_audio
except Exception:
 sdl2_audio=None

PROJECT_DIR=os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE=os.path.join(PROJECT_DIR,'local_settings.json')
SOUNDS_DIR=r'C:\Sounds'
alerts=deque(maxlen=100)
_last_health={}
_audio_lock=threading.RLock()

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

def initialize_audio_device(device=None,persist=False):
 settings=load_settings(); wanted=(device if device is not None else settings.get('audio_device','')) or ''
 wanted=str(wanted).strip()
 with _audio_lock:
  if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
   return False,'Existe um alerta em reprodução. Pare o áudio antes de trocar a saída.'
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
   settings['audio_device']=wanted
   save_settings(settings)
  return True,None

def spotify_info():
 found=False; vols=[]
 comtypes.CoInitialize()
 try:
  for s in AudioUtilities.GetAllSessions():
   try:
    if s.Process and s.Process.name().lower()=='spotify.exe':
     found=True; vols.append(float(s.SimpleAudioVolume.GetMasterVolume()))
   except Exception:pass
 finally:comtypes.CoUninitialize()
 return {'running':found,'volume':round(max(vols),2) if vols else None,'sessions':len(vols)}

def health_snapshot():
 usage=shutil.disk_usage(PROJECT_DIR)
 sounds_ok=os.path.isdir(SOUNDS_DIR) and os.access(SOUNDS_DIR,os.R_OK)
 try:mixer_ok=bool(pygame.mixer.get_init())
 except Exception:mixer_ok=False
 sp=spotify_info(); devices=audio_devices(); selected=selected_audio_device()
 return {
  'time':datetime.now().isoformat(timespec='seconds'),
  'hostname':socket.gethostname(),
  'friendly_name':'audioserver.local',
  'sounds_directory':SOUNDS_DIR,
  'sounds_directory_ok':sounds_ok,
  'audio_mixer_ok':mixer_ok,
  'audio_device':selected or 'Padrão do Windows',
  'audio_devices':devices,
  'spotify':sp,
  'disk_free_gb':round(usage.free/(1024**3),2),
  'disk_total_gb':round(usage.total/(1024**3),2),
  'cpu_percent':psutil.cpu_percent(interval=.1),
  'memory_percent':psutil.virtual_memory().percent,
 }

def emit_alert(kind,message,severity='warning'):
 item={'time':datetime.now().isoformat(timespec='seconds'),'kind':kind,'message':message,'severity':severity}
 alerts.appendleft(item)
 settings=load_settings(); cfg=settings.get('failure_alerts',{})
 url=(cfg.get('webhook_url') or '').strip()
 if cfg.get('enabled') and url:
  def send():
   try:
    body=json.dumps({'source':'AudioServer',**item}).encode('utf-8')
    req=urllib.request.Request(url,data=body,headers={'Content-Type':'application/json'},method='POST')
    urllib.request.urlopen(req,timeout=5).read()
   except Exception:pass
  threading.Thread(target=send,daemon=True).start()

def monitor_loop():
 global _last_health
 while True:
  try:
   h=health_snapshot()
   checks={
    'sounds_directory':(h['sounds_directory_ok'],'Pasta C:\\Sounds indisponível'),
    'audio_mixer':(h['audio_mixer_ok'],'Mixer de áudio não está disponível'),
    'spotify':(h['spotify']['running'],'Spotify não foi encontrado'),
    'disk_space':(h['disk_free_gb']>=5,f"Pouco espaço em disco: {h['disk_free_gb']} GB livres"),
   }
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
 h=health_snapshot(); h['alerts']=list(alerts); h['failure_alerts']=load_settings().get('failure_alerts',{'enabled':False,'webhook_url':''})
 try:h['audit_database']=audit_database_info()
 except Exception:h['audit_database']={'events':0,'size_bytes':0}
 return jsonify(h)

@bp.get('/api/audit')
def audit_api():
 try:limit=int(request.args.get('limit','250'))
 except Exception:limit=250
 try:return jsonify({'events':audit_recent_events(limit)})
 except Exception as exc:return jsonify({'error':str(exc),'events':[]}),500

@bp.get('/api/metrics')
def metrics_api():
 try:days=int(request.args.get('days','7'))
 except Exception:days=7
 try:return jsonify(audit_metrics(days))
 except Exception as exc:return jsonify({'error':str(exc)}),500

@bp.get('/api/audio-devices')
def audio_devices_api():
 devices=audio_devices(); selected=selected_audio_device()
 settings=load_settings(); configured=settings.get('alert_outputs',[])
 cfg={str(x.get('device') or '').strip():x for x in configured if isinstance(x,dict)}
 items=[]
 for d in devices:
  x=cfg.get(d,{})
  items.append({'name':d,'available':True,'selected':d in cfg,'volume':float(x.get('volume',1.0)),'delay_ms':int(x.get('delay_ms',0))})
 return jsonify({'devices':devices,'device_status':items,'selected':selected,'display_selected':selected or 'Padrão do Windows','mixer_ready':bool(pygame.mixer.get_init())})

@bp.post('/config/audio-device')
def configure_audio_device():
 data=request.get_json(silent=True) or {}; device=str(data.get('device') or '').strip(); devices=audio_devices()
 if device and devices and device not in devices:return jsonify({'error':'Dispositivo não encontrado. Atualize a lista e tente novamente.'}),400
 ok,err=initialize_audio_device(device,persist=True)
 if not ok:return jsonify({'error':f'Não foi possível ativar a saída: {err}'}),409
 return jsonify({'status':'ok','selected':device,'display_selected':device or 'Padrão do Windows'})

@bp.post('/config/failure-alerts')
def configure_alerts():
 data=request.get_json(silent=True) or {}; settings=load_settings(); cfg=settings.setdefault('failure_alerts',{})
 if 'enabled' in data:cfg['enabled']=bool(data['enabled'])
 if 'webhook_url' in data:cfg['webhook_url']=str(data['webhook_url']).strip()
 save_settings(settings); return jsonify({'failure_alerts':cfg})

@bp.post('/diagnostics/test-alert')
def test_alert():
 emit_alert('test','Alerta de teste do AudioServer','info'); return jsonify({'status':'sent'})

@bp.after_app_request
def inject_music_dashboard_link(response):
 """Mantém o atalho de Música Ambiente visível no painel principal sem duplicar a lógica da página."""
 try:
  if request.path=='/' and response.content_type and response.content_type.startswith('text/html'):
   text=response.get_data(as_text=True)
   if '/static/music.html' not in text:
    marker='<a class="linkbtn" href="/static/audio-output.html">🔊 Saída de áudio</a>'
    replacement=marker+'<a class="linkbtn" href="/static/music.html">🎵 Música ambiente</a>'
    if marker in text:
     response.set_data(text.replace(marker,replacement,1))
     response.headers['Content-Length']=len(response.get_data())
 except Exception:pass
 return response

try:initialize_audio_device(selected_audio_device(),persist=False)
except Exception:pass
threading.Thread(target=audit_tail_loop,daemon=True).start()
threading.Thread(target=monitor_loop,daemon=True).start()
