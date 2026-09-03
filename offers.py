"""Campanhas de ofertas e geração de locução via ElevenLabs."""
import json, os, re, urllib.request, urllib.error, uuid
from datetime import datetime
from flask import Blueprint, jsonify, request, send_file
from num2words import num2words

PROJECT_DIR=os.path.dirname(os.path.abspath(__file__)); DATA_FILE=os.path.join(PROJECT_DIR,'offers.json'); OUTPUT_DIR=r'C:\Sounds\Ofertas'; bp=Blueprint('offers',__name__)
V3_STABILITIES=(0.0,0.5,1.0)

def _v3_stability(value):
 try:value=float(value)
 except Exception:return .5
 return min(V3_STABILITIES,key=lambda x:abs(x-value))
def _load():
 try:
  with open(DATA_FILE,'r',encoding='utf-8') as f:data=json.load(f)
 except Exception:data={'campaigns':[],'settings':{}}
 cfg=data.setdefault('settings',{});cfg.setdefault('voice_id','');cfg['model_id']='eleven_v3';cfg['stability']=_v3_stability(cfg.get('stability',.5))
 for k in ('similarity_boost','style','speed','use_speaker_boost'):cfg.pop(k,None)
 data.setdefault('campaigns',[]);return data
def _save(data):
 with open(DATA_FILE,'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
def settings():return _load()['settings']
def list_campaigns():return _load()['campaigns']
def get_campaign(cid):return next((x for x in list_campaigns() if x.get('id')==cid),None)
def save_settings(payload):
 data=_load();cfg=data['settings'];cfg['voice_id']=str(payload.get('voice_id',cfg.get('voice_id','')) or '').strip();cfg['model_id']='eleven_v3';cfg['stability']=_v3_stability(payload.get('stability',cfg.get('stability',.5)));_save(data);return cfg

def price_words(v):
 try:
  s=str(v).strip().replace('R$','').strip().replace('.','').replace(',','.');n=round(float(s)+1e-9,2);r=int(n);c=int(round((n-r)*100));p=[]
  if r:p.append(f"{num2words(r,lang='pt_BR')} {'real' if r==1 else 'reais'}")
  if c:p.append(f"{num2words(c,lang='pt_BR')} {'centavo' if c==1 else 'centavos'}")
  return ' e '.join(p) or 'zero reais'
 except Exception:return str(v)

# Frases propositalmente curtas: o ritmo vem das pausas entre produtos, não de
# conectivos em todas as linhas. Isso deixa a locução mais parecida com rádio de varejo.
STYLES={
 'natural':{
  'intro':'Atenção para as ofertas!',
  'leads':['Olha só:','','','Confira:','',''],
  'prices':['por','por apenas','só','por','por apenas','só'],
  'outro':'Aproveite as ofertas e boas compras!'},
 'animated':{
  'intro':'Atenção! Ofertas especiais para você!',
  'leads':['Super oferta:','','Olha essa:','','Aproveite:',''],
  'prices':['por apenas','só','por','só','por apenas','por'],
  'outro':'Aproveite! Ofertas por tempo limitado. Boas compras!'},
 'institutional':{
  'intro':'Confira nossas ofertas.',
  'leads':['','','Confira também:','','',''],
  'prices':['por','por','por apenas','por','por','por apenas'],
  'outro':'Aproveite nossas ofertas. Agradecemos a preferência!'},
 'fresh':{
  'intro':'Ofertas fresquinhas para você!',
  'leads':['Olha só:','','Aproveite:','','',''],
  'prices':['por','só','por apenas','por','só','por'],
  'outro':'Aproveite as ofertas do setor e boas compras!'}
}

def build_script(name,items,intro='',outro='',script_style='natural'):
 style=STYLES.get(script_style,STYLES['natural']);valid=[x for x in items if str(x.get('product') or '').strip()];parts=[intro.strip() or style['intro']];total=len(valid)
 for i,x in enumerate(valid):
  product=str(x.get('product') or '').strip();detail=str(x.get('detail') or '').strip();lead=style['leads'][i%len(style['leads'])];pricelead=style['prices'][i%len(style['prices'])]
  # Em listas grandes eliminamos quase todos os conectivos e deixamos produto/preço respirar.
  if total>=7:lead='Confira:' if i and i%4==0 else ''
  desc=f'{product}{", " + detail if detail else ""}'
  prefix=(lead+' ') if lead else ''
  parts.append(f'{prefix}{desc}... {pricelead} {price_words(x.get("price",""))}!')
 parts.append(outro.strip() or style['outro']);return '\n\n'.join(parts)

def save_campaign(payload):
 data=_load();cs=data['campaigns'];cid=str(payload.get('id') or uuid.uuid4().hex[:10]);now=datetime.now().isoformat(timespec='seconds');old=next((x for x in cs if x.get('id')==cid),None)
 items=[{'product':str(x.get('product') or '').strip(),'price':x.get('price',''),'detail':str(x.get('detail') or '').strip()} for x in payload.get('items',[]) if str(x.get('product') or '').strip()]
 style=str(payload.get('script_style') or (old.get('script_style') if old else 'natural') or 'natural');style=style if style in STYLES else 'natural'
 c={'id':cid,'name':str(payload.get('name') or 'Ofertas').strip(),'start':str(payload.get('start') or ''),'end':str(payload.get('end') or ''),'interval_minutes':max(1,int(payload.get('interval_minutes',30))),'enabled':bool(payload.get('enabled',old.get('enabled',False) if old else False)),'items':items,'intro':str(payload.get('intro') or ''),'outro':str(payload.get('outro') or ''),'script_style':style,'script':str(payload.get('script') or '').strip(),'audio_sound':str(payload.get('audio_sound') or ''),'workflow_status':str(payload.get('workflow_status') or (old.get('workflow_status') if old else 'draft')),'updated_at':now}
 if not c['script']:c['script']=build_script(c['name'],items,c['intro'],c['outro'],style)
 if old:
  c['created_at']=old.get('created_at',now);c['audio_sound']=c['audio_sound'] or old.get('audio_sound','')
  if old.get('audio_generated_at'):c['audio_generated_at']=old['audio_generated_at']
  cs[cs.index(old)]=c
 else:c['created_at']=now;cs.append(c)
 _save(data);return c
def delete_campaign(cid):
 data=_load();before=len(data['campaigns']);data['campaigns']=[x for x in data['campaigns'] if x.get('id')!=cid];_save(data);return len(data['campaigns'])<before
def audio_path(c):
 sound=str((c or {}).get('audio_sound') or '').strip();p=os.path.abspath(os.path.join(OUTPUT_DIR,sound+'.mp3')) if sound else '';root=os.path.abspath(OUTPUT_DIR)+os.sep;return p if p and p.startswith(root) and os.path.isfile(p) else None
def set_status(cid,status):
 if status not in {'draft','narrated','approved','published'}:return False,None
 data=_load();found=None
 for c in data['campaigns']:
  if c.get('id')==cid:c['workflow_status']=status;c['enabled']=status=='published';c['updated_at']=datetime.now().isoformat(timespec='seconds');found=c;break
 if found:_save(data)
 return bool(found),found

def generate_audio(cid):
 key=os.environ.get('ELEVENLABS_API_KEY','').strip();cfg=settings();voice=str(cfg.get('voice_id','')).strip();c=get_campaign(cid)
 if not key:return False,'Configure ELEVENLABS_API_KEY no Windows.',None
 if not voice:return False,'Configure o Voice ID da ElevenLabs.',None
 if not c:return False,'Campanha não encontrada.',None
 text=str(c.get('script') or '').strip()
 if not text:return False,'Roteiro vazio.',None
 body={'text':text,'model_id':'eleven_v3','voice_settings':{'stability':_v3_stability(cfg.get('stability',.5))}}
 req=urllib.request.Request(f'https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128',data=json.dumps(body).encode('utf-8'),method='POST',headers={'xi-api-key':key,'Content-Type':'application/json','Accept':'audio/mpeg'})
 try:
  with urllib.request.urlopen(req,timeout=90) as r:audio=r.read()
 except urllib.error.HTTPError as e:
  try:msg=e.read().decode('utf-8','replace')[:500]
  except Exception:msg=str(e)
  return False,f'ElevenLabs: {e.code} {msg}',None
 except Exception as e:return False,str(e),None
 os.makedirs(OUTPUT_DIR,exist_ok=True);safe=re.sub(r'[^A-Za-z0-9_-]+','-',c['name']).strip('-') or 'Oferta';filename=f'Oferta-{safe}-{cid}.mp3';path=os.path.join(OUTPUT_DIR,filename)
 with open(path,'wb') as f:f.write(audio)
 data=_load()
 for x in data['campaigns']:
  if x.get('id')==cid:x['audio_sound']=os.path.splitext(filename)[0];x['audio_generated_at']=datetime.now().isoformat(timespec='seconds');x['workflow_status']='narrated';x['enabled']=False
 _save(data);return True,None,path

@bp.get('/offers')
def offers_get():return jsonify({'campaigns':list_campaigns(),'settings':settings(),'script_styles':[{'id':'natural','name':'Comercial natural'},{'id':'animated','name':'Oferta animada'},{'id':'institutional','name':'Institucional'},{'id':'fresh','name':'Hortifruti / Açougue'}],'api_key_configured':bool(os.environ.get('ELEVENLABS_API_KEY','').strip())})
@bp.post('/offers/settings')
def offers_settings():return jsonify({'settings':save_settings(request.get_json(silent=True) or {})})
@bp.post('/offers/script')
def offers_script():
 d=request.get_json(silent=True) or {};return jsonify({'script':build_script(str(d.get('name') or 'Ofertas'),d.get('items') or [],str(d.get('intro') or ''),str(d.get('outro') or ''),str(d.get('script_style') or 'natural'))})
@bp.post('/offers/campaigns')
def offers_save():return jsonify({'campaign':save_campaign(request.get_json(silent=True) or {})})
@bp.post('/offers/campaigns/delete')
def offers_delete():return jsonify({'deleted':delete_campaign(str((request.get_json(silent=True) or {}).get('id') or ''))})
@bp.post('/offers/narrate')
def offers_narrate():
 cid=str((request.get_json(silent=True) or {}).get('id') or '');ok,err,path=generate_audio(cid)
 if not ok:return jsonify({'error':err}),409
 c=get_campaign(cid);return jsonify({'status':'narrated','sound':c.get('audio_sound'),'preview_url':f'/offers/audio/{cid}'})
@bp.get('/offers/audio/<cid>')
def offers_audio(cid):
 p=audio_path(get_campaign(cid))
 if not p:return jsonify({'error':'Narração não encontrada'}),404
 return send_file(p,mimetype='audio/mpeg',conditional=True,download_name=os.path.basename(p))
@bp.post('/offers/status')
def offers_status():
 d=request.get_json(silent=True) or {};ok,c=set_status(str(d.get('id') or ''),str(d.get('status') or ''))
 return jsonify({'campaign':c}) if ok else (jsonify({'error':'Campanha ou status inválido'}),400)
