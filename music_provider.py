"""Camada de provedores de música ambiente do AudioServer.

A interface web conversa somente com este módulo. Assim podemos começar
controlando o Spotify Desktop local e futuramente adicionar Biblioteca Local,
AzuraCast ou Soundtrack sem redesenhar o painel.
"""
import os
import subprocess
import time

import comtypes
from pycaw.pycaw import AudioUtilities

try:
 import win32api
except Exception:
 win32api=None


class MusicProvider:
    id='none'
    name='Nenhum'
    def status(self): return {'provider':self.id,'provider_name':self.name,'available':False,'playing':False,'track':None}
    def command(self,command): return False,'Comando não suportado'


class SpotifyDesktopProvider(MusicProvider):
    id='spotify'
    name='Spotify Desktop'

    def _sessions(self):
        sessions=[]
        comtypes.CoInitialize()
        try:
            for s in AudioUtilities.GetAllSessions():
                try:
                    if s.Process and s.Process.name().lower()=='spotify.exe': sessions.append(s)
                except Exception: pass
        finally:
            comtypes.CoUninitialize()
        return sessions

    def status(self):
        running=False; volume=None
        comtypes.CoInitialize()
        try:
            vals=[]
            for s in AudioUtilities.GetAllSessions():
                try:
                    if s.Process and s.Process.name().lower()=='spotify.exe':
                        running=True; vals.append(float(s.SimpleAudioVolume.GetMasterVolume()))
                except Exception: pass
            if vals: volume=max(vals)
        finally:
            comtypes.CoUninitialize()
        # Sem OAuth/API, o Windows fornece transporte e volume, mas não metadados
        # confiáveis da faixa. Mantemos esses campos para provedores futuros.
        return {'provider':self.id,'provider_name':self.name,'available':running,'playing':running,'track':None,'artist':None,'album':None,'artwork':None,'volume':volume,'capabilities':['play_pause','previous','next','volume']}

    def _media_key(self,command):
        # VK_MEDIA_*: previous 0xB1, next 0xB0, play/pause 0xB3.
        keys={'previous':0xB1,'next':0xB0,'play_pause':0xB3}
        vk=keys.get(command)
        if not vk or win32api is None:return False,'pywin32 não está disponível'
        try:
            win32api.keybd_event(vk,0,0,0); win32api.keybd_event(vk,0,2,0); return True,None
        except Exception as exc:return False,str(exc)

    def command(self,command):
        if command in ('previous','next','play_pause'):return self._media_key(command)
        return False,'Comando não suportado'

    def set_volume(self,value):
        value=max(0.0,min(1.0,float(value))); changed=0
        comtypes.CoInitialize()
        try:
            for s in AudioUtilities.GetAllSessions():
                try:
                    if s.Process and s.Process.name().lower()=='spotify.exe':s.SimpleAudioVolume.SetMasterVolume(value,None);changed+=1
                except Exception:pass
        finally:comtypes.CoUninitialize()
        return (changed>0,None if changed else 'Spotify não encontrado')


PROVIDERS={'spotify':SpotifyDesktopProvider()}

def get_provider(provider_id):return PROVIDERS.get(provider_id) or PROVIDERS['spotify']
def provider_catalog():
    return [
      {'id':'spotify','name':'Spotify Desktop','implemented':True},
      {'id':'local','name':'Biblioteca local','implemented':False},
      {'id':'azuracast','name':'AzuraCast','implemented':False},
      {'id':'soundtrack','name':'Soundtrack','implemented':False},
    ]
