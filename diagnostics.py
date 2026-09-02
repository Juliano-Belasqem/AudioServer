import json, os, shutil, socket, threading, time, urllib.request
from collections import deque
from datetime import datetime

import psutil
import pygame
from flask import Blueprint, jsonify, render_template, request
from pycaw.pycaw import AudioUtilities
import comtypes

PROJECT_DIR=os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE=os.path.join(PROJECT_DIR,'local_settings.json')
SOUNDS_DIR=r'C:\Sounds'
alerts=deque(maxlen=100)
_last_health={}

bp=Blueprint('diagnostics',__name__)

def load_settings():
 try:
  with open(SETTINGS_FILE,'r',encoding='utf-8') as f:return json.load(f)
 except Exception:return {}

def save_settings(settings):
 with open(SETTINGS_FILE,'w',encoding='utf-8') as f:json.dump(settings,f,ensure_ascii=False,indent=2)

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
 try:
  mixer_ok=bool(pygame.mixer.get_init())
 except Exception:mixer_ok=False
 sp=spotify_info()
 return {
  'time':datetime.now().isoformat(timespec='seconds'),
  'hostname':socket.gethostname(),
  'friendly_name':'audioserver.local',
  'sounds_directory':SOUNDS_DIR,
  'sounds_directory_ok':sounds_ok,
  'audio_mixer_ok':mixer_ok,
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
 return jsonify(h)

@bp.post('/config/failure-alerts')
def configure_alerts():
 data=request.get_json(silent=True) or {}; settings=load_settings(); cfg=settings.setdefault('failure_alerts',{})
 if 'enabled' in data:cfg['enabled']=bool(data['enabled'])
 if 'webhook_url' in data:cfg['webhook_url']=str(data['webhook_url']).strip()
 save_settings(settings); return jsonify({'failure_alerts':cfg})

@bp.post('/diagnostics/test-alert')
def test_alert():
 emit_alert('test','Alerta de teste do AudioServer','info'); return jsonify({'status':'sent'})

threading.Thread(target=monitor_loop,daemon=True).start()
