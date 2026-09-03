import json, os, shutil, socket, threading, time, urllib.request
from collections import deque
from datetime import datetime

import psutil
import pygame
from flask import Blueprint, jsonify, render_template, request
from pycaw.pycaw import AudioUtilities
import comtypes
from audit_store import tail_loop as audit_tail_loop, recent_events as audit_recent_events, metrics as audit_metrics, database_info as audit_database_info
import offers

try:
 from pygame._sdl2 import audio as sdl2_audio
except Exception:
 sdl2_audio=None

PROJECT_DIR=os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE=os.path.join(PROJECT_DIR,'local_settings.json')
SOUNDS_DIR=r'C:\Sounds'
alerts=deque(maxlen=100); _last_health={}; _audio_lock=threading.RLock(); _offer_fired={}
bp=Blueprint('diagnostics',__name__)

def load_settings():
 try:
  with open(SETTINGS_FILE,'r',encoding='utf-8') as f:return json.load(f)
 except Exception:return {}
def save_settings(settings):
 with open(SETTINGS_FILE,'w',encoding='utf-8') as f:json.dump(settings,f,ensure_ascii=False,indent=2)
def audio_devices():
 try:return [] if sdl2_audio is None else [str(x) for x in sdl2_audio.get_audio_device_names(False)]
 except Exception:return []
def selected_audio_device():return (load_settings().get('audio_device') or '').strip()
def initialize_audio_device(device=None,persist=False):
 settings=load_settings();wanted=str((device if device is not None else settings.get('audio_device','')) or '').strip()
 with _audio_lock:
  if pygame.mixer.get_init() and pygame.mixer.music.get_busy():return False,'Existe um alerta em reprodução. Pare o áudio antes de trocar a saída.'
  previous_volume=float(settings.get('volume',1.0))
  try:
   if pygame.mixer.get_init():pygame.mixer.quit()
   pygame.mixer.init(devicename=wanted) if wanted else pygame.mixer.init();pygame.mixer.music.set_volume(max(0,min(1,previous_volume)))
  except Exception as exc:
   try:
    if pygame.mixer.get_init():pygame.mixer.quit()
    pygame.mixer.init();pygame.mixer.music.set_volume(max(0,min(1,previous_volume)))
   except Exception:pass
   return False,str(exc)
  if persist:settings['audio_device']=wanted;save_settings(settings)
  return True,None
def spotify_info():
 found=False;vols=[];comtypes.CoInitialize()
 try:
  for s in AudioUtilities.GetAllSessions():
   try:
    if s.Process and s.Process.name().lower()=='spotify.exe':found=True;vols.append(float(s.SimpleAudioVolume.GetMasterVolume()))
   except Exception:pass
 finally:comtypes.CoUninitialize()
 return {'running':found,'volume':round(max(vols),2) if vols else None,'sessions':len(vols)}
def health_snapshot():
 usage=shutil.disk_usage(PROJECT_DIR);sounds_ok=os.path.isdir(SOUNDS_DIR) and os.access(SOUNDS_DIR,os.R_OK)
 try:mixer_ok=bool(pygame.mixer.get_init())
 except Exception:mixer_ok=False
 sp=spotify_info();devices=audio_devices();selected=selected_audio_device()
 return {'time':datetime.now().isoformat(timespec='seconds'),'hostname':socket.gethostname(),'friendly_name':'audioserver.local','sounds_directory':SOUNDS_DIR,'sounds_directory_ok':sounds_ok,'audio_mixer_ok':mixer_ok,'audio_device':selected or 'Padrão do Windows','audio_devices':devices,'spotify':sp,'disk_free_gb':round(usage.free/(1024**3),2),'disk_total_gb':round(usage.total/(1024**3),2),'cpu_percent':psutil.cpu_percent(interval=.1),'memory_percent':psutil.virtual_memory().percent}
def emit_alert(kind,message,severity='warning'):
 item={'time':datetime.now().isoformat(timespec='seconds'),'kind':kind,'message':message,'severity':severity};alerts.appendleft(item);cfg=load_settings().get('failure_alerts',{});url=(cfg.get('webhook_url') or '').strip()
 if cfg.get('enabled') and url:
  def send():
   try:
    body=json.dumps({'source':'AudioServer',**item}).encode();urllib.request.urlopen(urllib.request.Request(url,data=body,headers={'Content-Type':'application/json'},method='POST'),timeout=5).read()
   except Exception:pass
  threading.Thread(target=send,daemon=True).start()
def monitor_loop():
 global _last_health
 while True:
  try:
   h=health_snapshot();checks={'sounds_directory':(h['sounds_directory_ok'],'Pasta C:\\Sounds indisponível'),'audio_mixer':(h['audio_mixer_ok'],'Mixer de áudio não está disponível'),'spotify':(h['spotify']['running'],'Spotify não foi encontrado'),'disk_space':(h['disk_free_gb']>=5,f"Pouco espaço em disco: {h['disk_free_gb']} GB livres")}
   for key,(ok,msg) in checks.items():
    previous=_last_health.get(key,True)
    if previous and not ok:emit_alert(key,msg,'error')
    elif not previous and ok:emit_alert(key,f'{key} normalizado','info')
    _last_health[key]=ok
  except Exception:pass
  time.sleep(60)
def _parse_dt(value):
 try:return datetime.fromisoformat(str(value))
 except Exception:return None
def offer_scheduler():
 while True:
  try:
   now=datetime.now()
   for c in offers.list_campaigns():
    if not c.get('enabled') or not c.get('audio_sound'):continue
    start=_parse_dt(c.get('start'));end=_parse_dt(c.get('end'))
    if start and now<start:continue
    if end and now>end:continue
    interval=max(1,int(c.get('interval_minutes',30)));anchor=start or now.replace(hour=0,minute=0,second=0,microsecond=0);elapsed=max(0,(now-anchor).total_seconds());slot=int(elapsed//(interval*60));key=f"{c.get('id')}:{anchor.date()}:{slot}"
    if key in _offer_fired:continue
    due=anchor.timestamp()+slot*interval*60
    if 0<=now.timestamp()-due<70:
     body=json.dumps({'sound':c['audio_sound']}).encode();req=urllib.request.Request('http://127.0.0.1:8765/play',data=body,headers={'Content-Type':'application/json'},method='POST')
     try:urllib.request.urlopen(req,timeout=8).read();_offer_fired[key]=time.time()
     except Exception:pass
   cutoff=time.time()-86400*4
   for k,v in list(_offer_fired.items()):
    if v<cutoff:_offer_fired.pop(k,None)
  except Exception:pass
  time.sleep(20)

@bp.get('/diagnostics')
def diagnostics_page():return render_template('diagnostics.html')
@bp.get('/api/diagnostics')
def diagnostics_api():
 h=health_snapshot();h['alerts']=list(alerts);h['failure_alerts']=load_settings().get('failure_alerts',{'enabled':False,'webhook_url':''})
 try:h['audit_database']=audit_database_info()
 except Exception:h['audit_database']={'events':0,'size_bytes':0}
 return jsonify(h)
@bp.get('/api/audit')
def audit_api():
 try:limit=int(request.args.get('limit','250'));return jsonify({'events':audit_recent_events(limit)})
 except Exception as exc:return jsonify({'error':str(exc),'events':[]}),500
@bp.get('/api/metrics')
def metrics_api():
 try:return jsonify(audit_metrics(int(request.args.get('days','7'))))
 except Exception as exc:return jsonify({'error':str(exc)}),500
@bp.get('/api/audio-devices')
def audio_devices_api():
 devices=audio_devices();selected=selected_audio_device();configured=load_settings().get('alert_outputs',[]);cfg={str(x.get('device') or '').strip():x for x in configured if isinstance(x,dict)};items=[]
 for d in devices:
  x=cfg.get(d,{});items.append({'name':d,'available':True,'selected':d in cfg,'volume':float(x.get('volume',1.0)),'delay_ms':int(x.get('delay_ms',0))})
 return jsonify({'devices':devices,'device_status':items,'selected':selected,'display_selected':selected or 'Padrão do Windows','mixer_ready':bool(pygame.mixer.get_init())})
@bp.post('/config/audio-device')
def configure_audio_device():
 data=request.get_json(silent=True) or {};device=str(data.get('device') or '').strip();devices=audio_devices()
 if device and devices and device not in devices:return jsonify({'error':'Dispositivo não encontrado. Atualize a lista e tente novamente.'}),400
 ok,err=initialize_audio_device(device,persist=True)
 if not ok:return jsonify({'error':f'Não foi possível ativar a saída: {err}'}),409
 return jsonify({'status':'ok','selected':device,'display_selected':device or 'Padrão do Windows'})
@bp.post('/config/failure-alerts')
def configure_alerts():
 data=request.get_json(silent=True) or {};settings=load_settings();cfg=settings.setdefault('failure_alerts',{})
 if 'enabled' in data:cfg['enabled']=bool(data['enabled'])
 if 'webhook_url' in data:cfg['webhook_url']=str(data['webhook_url']).strip()
 save_settings(settings);return jsonify({'failure_alerts':cfg})
@bp.post('/diagnostics/test-alert')
def test_alert():emit_alert('test','Alerta de teste do AudioServer','info');return jsonify({'status':'sent'})

@bp.after_app_request
def inject_dashboard_links(response):
 try:
  if request.path=='/' and response.content_type and response.content_type.startswith('text/html'):
   text=response.get_data(as_text=True);marker='<a class="linkbtn" href="/static/audio-output.html">🔊 Saída de áudio</a>';extra=''
   if '/static/music.html' not in text:extra+='<a class="linkbtn" href="/static/music.html">🎵 Música ambiente</a>'
   if '/static/offers.html' not in text:extra+='<a class="linkbtn" href="/static/offers.html">📣 Ofertas</a>'
   if marker in text and extra:response.set_data(text.replace(marker,marker+extra,1));response.headers['Content-Length']=len(response.get_data())
 except Exception:pass
 return response

try:initialize_audio_device(selected_audio_device(),persist=False)
except Exception:pass
threading.Thread(target=audit_tail_loop,daemon=True).start();threading.Thread(target=monitor_loop,daemon=True).start();threading.Thread(target=offer_scheduler,daemon=True).start()
