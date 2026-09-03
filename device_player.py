import argparse, sys, threading, time
import pygame

parser=argparse.ArgumentParser()
parser.add_argument('--file',required=True)
parser.add_argument('--device',default='')
parser.add_argument('--volume',type=float,default=1.0)
parser.add_argument('--fade-in-ms',type=int,default=0)
args=parser.parse_args()

device=args.device.strip() or None
pygame.mixer.init(devicename=device)
pygame.mixer.music.set_volume(max(0.0,min(1.0,args.volume)))
pygame.mixer.music.load(args.file)
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
