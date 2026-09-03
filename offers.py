"""Campanhas de ofertas e geração de locução via ElevenLabs.
A chave nunca é persistida no repositório: use ELEVENLABS_API_KEY no Windows.
"""
import json, os, re, urllib.request, urllib.error, uuid
from datetime import datetime

PROJECT_DIR=os.path.dirname(os.path.abspath(__file__))
DATA_FILE=os.path.join(PROJECT_DIR,'offers.json')
OUTPUT_DIR=r'C:\Sounds\Ofertas'

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
    c={'id':cid,'name':str(payload.get('name') or 'Ofertas').strip(),'start':str(payload.get('start') or ''),'end':str(payload.get('end') or ''),'interval_minutes':max(1,int(payload.get('interval_minutes',30))),'enabled':bool(payload.get('enabled',True)),'items':items,'intro':str(payload.get('intro') or ''),'outro':str(payload.get('outro') or ''),'script':str(payload.get('script') or '').strip(),'audio_sound':str(payload.get('audio_sound') or ''),'updated_at':now}
    if not c['script']:c['script']=build_script(c['name'],items,c['intro'],c['outro'])
    old=next((x for x in campaigns if x.get('id')==cid),None)
    if old:
        c['created_at']=old.get('created_at',now)
        if not c['audio_sound']:c['audio_sound']=old.get('audio_sound','')
        campaigns[campaigns.index(old)]=c
    else:c['created_at']=now;campaigns.append(c)
    _save(data);return c
def delete_campaign(cid):
    data=_load();before=len(data.get('campaigns',[]));data['campaigns']=[x for x in data.get('campaigns',[]) if x.get('id')!=cid];_save(data);return len(data['campaigns'])<before
def get_campaign(cid):return next((x for x in list_campaigns() if x.get('id')==cid),None)
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
        if x.get('id')==cid:x['audio_sound']=os.path.splitext(filename)[0];x['audio_generated_at']=datetime.now().isoformat(timespec='seconds')
    _save(data);return True,None,path
