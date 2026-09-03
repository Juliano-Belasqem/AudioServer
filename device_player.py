import argparse, json, os, sys, threading, time
import pygame

parser=argparse.ArgumentParser()
parser.add_argument('--file',required=True)
parser.add_argument('--device',default='')
parser.add_argument('--volume',type=float,default=1.0)
parser.add_argument('--fade-in-ms',type=int,default=0)
parser.add_argument('--delay-ms',type=int,default=None)
args=parser.parse_args()

def configured_delay(device):
    if args.delay_ms is not None:
        return max(0,min(5000,args.delay_ms))
    try:
        settings_path=os.path.join(os.path.dirname(os.path.abspath(__file__)),'local_settings.json')
        with open(settings_path,'r',encoding='utf-8') as f:
            settings=json.load(f)
        wanted=(device or '').strip().lower()
        for output in settings.get('alert_outputs',[]):
            if str(output.get('device') or '').strip().lower()==wanted:
                return max(0,min(5000,int(output.get('delay_ms',0))))
    except Exception:
        pass
    return 0

device=args.device.strip() or None
delay_ms=configured_delay(device)
pygame.mixer.init(devicename=device)
pygame.mixer.music.set_volume(max(0.0,min(1.0,args.volume)))
pygame.mixer.music.load(args.file)
if delay_ms:
    time.sleep(delay_ms/1000.0)
pygame.mixer.music.play(fade_ms=max(0,args.fade_in_ms))

stop_event=threading.Event()

def control_loop():
    for line in sys.stdin:
        cmd=line.strip().lower()
        if cmd=='pause': pygame.mixer.music.pause()
        elif cmd=='resume': pygame.mixer.music.unpause()
        elif cmd=='stop':
            pygame.mixer.music.stop(); stop_event.set(); break

threading.Thread(target=control_loop,daemon=True).start()
while pygame.mixer.music.get_busy() and not stop_event.is_set():
    time.sleep(0.05)
pygame.mixer.quit()
