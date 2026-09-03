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

DEFAULT_SETTINGS={
    'voice_id':'','model_id':'eleven_multilingual_v2','preset':'comercial',
    'stability':0.38,'similarity_boost':0.78,'style':0.18,'speed':0.96,'use_speaker_boost':True
}

def _load():
    try:
        with open(DATA_FILE,'r',encoding='utf-8') as f:data=json.load(f)
    except Exception:data={'campaigns':[],'settings':{}}
    cfg=data.setdefault('settings',{})
    for k,v in DEFAULT_SETTINGS.items():cfg.setdefault(k,v)
    data.setdefault('campaigns',[])
    return data
def _save(data):
    with open(DATA_FILE,'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
def settings():return _load()['settings']
def save_settings(payload):
    data=_load();old=data['settings'];cfg=dict(DEFAULT_SETTINGS)
    cfg['voice_id']=str(payload.get('voice_id',old.get('voice_id','')) or '').strip()
    cfg['model_id']=str(payload.get('model_id',old.get('model_id','eleven_multilingual_v2')) or 'eleven_multilingual_v2').strip()
    cfg['preset']=str(payload.get('preset',old.get('preset','comercial')) or 'comercial')
    for key,default in [('stability',.38),('similarity_boost',.78),('style',.18),('speed',.96)]:
        try:cfg[key]=max(0.0,min(1.2 if key=='speed' else 1.0,float(payload.get(key,old.get(key,default)))))
        except Exception:cfg[key]=default
    cfg['speed']=max(.7,min(1.2,cfg['speed']))
    cfg['use_speaker_boost']=bool(payload.get('use_speaker_boost',old.get('use_speaker_boost',True)))
    data['settings']=cfg;_save(data);return cfg
def list_campaigns():return _load().get('campaigns',[])

_ONES=['zero','um','dois','três','quatro','cinco','seis','sete','oito','nove','dez','onze','doze','treze','quatorze','quinze','dezesseis','dezess