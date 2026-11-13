"""Read only: final own-PID and actual logged listener check on DARYU."""
import pathlib,json,re,socket,os,datetime
R=pathlib.Path('/opt/exp24-20261026-p5f/formal-v3')
c=json.loads((R/'cleanup.json').read_text());ports={50240,9024,50241,50242,50243}
for log in R.glob('client-*.log'):
 text=log.read_text();ports.update(map(int,re.findall(r'listening on 127\.0\.0\.1:(\d+)',text)))
 ports.update(map(int,re.findall(r'TcpTransport: listen on port (\d+)',text)))
checks={}
for port in sorted(ports):
 with socket.socket() as s:
  s.settimeout(.2);checks[str(port)]=s.connect_ex(('127.0.0.1',port))==0
pids={str(pid):pathlib.Path(f'/proc/{pid}').exists() for pid in c['owned_pids']}
r={'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'owned_pid_exists':pids,'actual_logged_and_static_port_listening':checks,
   'all_closed':not any(pids.values()) and not any(checks.values()),'scope':'own PIDs and loopback listener probes only; keys separately verified by Store is_exist, not physical memory zeroization'}
(R/'cleanup-live.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
assert r['all_closed']
