import atexit, socket
from zeroconf import IPVersion, ServiceInfo, Zeroconf

_zeroconf=None
_info=None

def start_mdns(port=8765):
 global _zeroconf,_info
 try:
  hostname=socket.gethostname()
  ip=socket.gethostbyname(hostname)
  if ip.startswith('127.'):
   s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
   try:s.connect(('8.8.8.8',80));ip=s.getsockname()[0]
   finally:s.close()
  _info=ServiceInfo('_http._tcp.local.','AudioServer._http._tcp.local.',addresses=[socket.inet_aton(ip)],port=port,properties={'path':'/'},server='audioserver.local.')
  _zeroconf=Zeroconf(ip_version=IPVersion.V4Only);_zeroconf.register_service(_info)
  return True
 except Exception:
  return False

def stop_mdns():
 try:
  if _zeroconf and _info:_zeroconf.unregister_service(_info)
  if _zeroconf:_zeroconf.close()
 except Exception:pass

atexit.register(stop_mdns)
