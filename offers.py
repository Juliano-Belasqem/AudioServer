"""Campanhas de ofertas e geração de locução via ElevenLabs.
A chave nunca é persistida no repositório: use ELEVENLABS_API_KEY no Windows.
"""
import json, os, re, urllib.request, urllib.error, uuid
from datetime import datetime
from flask import Blueprint, jsonify, request, send_file

PROJECT_DIR=os.path.dirname(os.path.abspath(__file__))
DATA_FILE=os.path.join(PROJECT_DIR,'offers.json')
OUTPUT_DIR=r'C:\Sounds\Ofertas'
bp=Blueprint('offers',__name__)

def _load():
    try:
        with open(DATA_FILE,'r',encoding='utf-8') as f:return json.load(f)
    except Exception:return {'campaigns':[],'settings':{'voice_id':'','model_id':'eleven_multilingual_v2'}}
def _save(data):
    with open(DATA_FILE,'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
def settings():return _load().setdefault('settings',{'voice_id':'','model_id':'eleven_multilingual_v2'})
def save_settings(voice_id,model_id='eleven_multilingual_v2'):
    data=_load();data['settings']={'voice_id':str(voice_id or '').strip(),'model_id':str(model_id or 'eleven_multilingual_v2').strip()};_save(data);return data['settings']
def list_campaigns():return _load().get('campaigns',[])
def money_pt(v):
    try:
        n=float(str(v).replace('.','').replace(',','.')) if isinstance(v,str) else float(v)
        return f'R$ {n:,.2f}'.replace(',','X').replace('.',',').replace('X','.')
    except Exception:return str(v)
def build_script(name,items,intro='',outro=''):
    parts=[intro.strip() or 'Atenção para as ofertas especiais do nosso supermercado!']
    for x in items:
        product=str(x.get('product') or '').strip();price=money_pt(x.get('price',''))
        detail=str(x.get('detail') or '').strip()
        if product:parts.append(f'{product}{", "+detail if detail else ""}, por apenas {price}.')
    parts.append(outro.strip() or 'Aproveite! Ofertas válidas enquanto durarem os estoques.')
    return ' '.join(parts)
def save_campaign(payload):
    data=_load();campaigns=data.setdefault('campaigns',[]);cid=str(payload.get('id') or uuid.uuid4().hex[:10]);now=datetime.now().isoformat(timespec='seconds')
    items=[{'product':str(x.get('product') or '').strip(),'price':x.get('price',''),'detail':str(x.get('detail') or '').strip()} for x in payload.get('items',[]) if str(x.get('product') or '').strip()]
    old=next((x for x in campaigns if x.get('id')==cid),None)
    c={'id':cid,'name':str(payload.get('name') or 'Ofertas').strip(),'start':str(payload.get('start') or ''),'end':str(payload.get('end') or ''),'interval_minutes':max(1,int(payload.get('interval_minutes',30))),'enabled':bool(payload.get('enabled',old.get('enabled',False) if old else False)),'items':items,'intro':str(payload.get('intro') or ''),'outro':str(payload.get('outro') or ''),'script':str(payload.get('script') or '').strip(),'audio_sound':str(payload.get('audio_sound') or ''),'workflow_status':str(payload.get('workflow_status') or (old.get('workflow_status') if old else 'draft') or 'draft'),'updated_at':now}
    if not c['script']:c['script']=build_script(c['name'],items,c['intro'],c['outro'])
    if old:
        c['created_at']=old.get('created_at',now)
        if not c['audio_sound']:c['audio_sound']=old.get('audio_sound','')
        if old.get('audio_generated_at'):c['audio_generated_at']=old['audio_generated_at']
        campaigns[campaigns.index(old)]=c
    else:c['created_at']=now;campaigns.append(c)
    _save(data);return c
def delete_campaign(cid):
    data=_load();before=len(data.get('campaigns',[]));data['campaigns']=[x for x in data.get('campaigns',[]) if x.get('id')!=cid];_save(data);return len(data['campaigns'])<before
def get_campaign(cid):return next((x for x in list_campaigns() if x.get('id')==cid),None)
def audio_path(c):
    sound=str((c or {}).get('audio_sound') or '').strip()
    if not sound:return None
    p=os.path.abspath(os.path.join(OUTPUT_DIR,sound+'.mp3'))
    root=os.path.abspath(OUTPUT_DIR)+os.sep
    return p if p.startswith(root) and os.path.isfile(p) else None
def set_status(cid,status):
    allowed={'draft','narrated','approved','published'}
    if status not in allowed:return False,None
    data=_load();found=None
    for c in data.get('campaigns',[]):
        if c.get('id')==cid:
            c['workflow_status']=status;c['enabled']=(status=='published');c['updated_at']=datetime.now().isoformat(timespec='seconds');found=c;break
    if found:_save(data)
    return bool(found),found
def generate_audio(cid):
    key=os.environ.get('ELEVENLABS_API_KEY','').strip();cfg=settings();voice=cfg.get('voice_id','').strip()
    if not key:return False,'Configure ELEVENLABS_API_KEY no Windows.',None
    if not voice:return False,'Configure o Voice ID da ElevenLabs.',None
    c=get_campaign(cid)
    if not c:return False,'Campanha não encontrada.',None
    text=str(c.get('script') or '').strip()
    if not text:return False,'Roteiro vazio.',None
    url=f'https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128'
    body=json.dumps({'text':text,'model_id':cfg.get('model_id') or 'eleven_multilingual_v2'}).encode('utf-8')
    req=urllib.request.Request(url,data=body,method='POST',headers={'xi-api-key':key,'Content-Type':'application/json','Accept':'audio/mpeg'})
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
    for x in data.get('campaigns',[]):
        if x.get('id')==cid:
            x['audio_sound']=os.path.splitext(filename)[0];x['audio_generated_at']=datetime.now().isoformat(timespec='seconds');x['workflow_status']='narrated';x['enabled']=False
    _save(data);return True,None,path

@bp.get('/offers')
def offers_get():return jsonify({'campaigns':list_campaigns(),'settings':settings(),'api_key_configured':bool(os.environ.get('ELEVENLABS_API_KEY','').strip())})
@bp.post('/offers/settings')
def offers_settings():
    d=request.get_json(silent=True) or {};return jsonify({'settings':save_settings(d.get('voice_id'),d.get('model_id'))})
@bp.post('/offers/script')
def offers_script():
    d=request.get_json(silent=True) or {};return jsonify({'script':build_script(str(d.get('name') or 'Ofertas'),d.get('items') or [],str(d.get('intro') or ''),str(d.get('outro') or ''))})
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
    c=get_campaign(cid);p=audio_path(c)
    if not p:return jsonify({'error':'Narração não encontrada'}),404
    return send_file(p,mimetype='audio/mpeg',conditional=True,download_name=os.path.basename(p))
@bp.post('/offers/status')
def offers_status():
    d=request.get_json(silent=True) or {};cid=str(d.get('id') or '');status=str(d.get('status') or '')
    ok,c=set_status(cid,status)
    if not ok:return jsonify({'error':'Campanha ou status inválido'}),400
    return jsonify({'campaign':c})
