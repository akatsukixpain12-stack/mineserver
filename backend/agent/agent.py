from __future__ import annotations
import asyncio,json,re,shutil,time,urllib.request,subprocess
from pathlib import Path
import psutil,websockets
ROOT=Path("/opt/minehub");SERVER=ROOT/"server";C=json.loads((ROOT/"config.json").read_text());BASE=C["control_url"].rstrip("/").replace("https://","wss://").replace("http://","ws://");URL=f"{BASE}/agent/ws?server_id={C['server_id']}&token={C['agent_token']}";MEM=int(C.get("memory_mb",2048));process=None;lock=asyncio.Lock();players=set();max_players=20
def safe(rel):
    p=(SERVER/rel.strip().replace("\\","/")).resolve()
    if p!=SERVER and SERVER not in p.parents:raise ValueError("Invalid path")
    return p
async def send(ws,x):
    async with lock:await ws.send(json.dumps(x))
def launch():
    global process
    if process and process.poll() is None:return
    process=subprocess.Popen(["java",f"-Xms{max(512,MEM//2)}M",f"-Xmx{MEM}M","-jar","server.jar","nogui"],cwd=SERVER,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
def stop():
    global process
    if not process or process.poll() is not None:return
    try:process.stdin.write("stop\n");process.stdin.flush();process.wait(timeout=30)
    except Exception:process.kill()
    process=None
def command(x):
    if not process or process.poll() is not None:raise RuntimeError("Minecraft is not running")
    process.stdin.write(x.lstrip("/")+"\n");process.stdin.flush()
def backup():
    b=ROOT/"backups";b.mkdir(exist_ok=True);name="backup-"+time.strftime("%Y%m%d-%H%M%S");return shutil.make_archive(str(b/name),"zip",root_dir=SERVER)
def download(url,target):
    folder=safe(target);folder.mkdir(parents=True,exist_ok=True);name=url.split("?")[0].rsplit("/",1)[-1] or "download.jar";out=folder/name;tmp=out.with_suffix(out.suffix+".part");req=urllib.request.Request(url,headers={"User-Agent":"MineHub-Agent/1.0"})
    with urllib.request.urlopen(req,timeout=90) as r,open(tmp,"wb") as f:shutil.copyfileobj(r,f)
    tmp.replace(out);return str(out.relative_to(SERVER))
def parse_player(line):
    m=re.search(r"([A-Za-z0-9_]{1,16}) joined the game",line)
    if m:players.add(m.group(1))
    m=re.search(r"([A-Za-z0-9_]{1,16}) left the game",line)
    if m:players.discard(m.group(1))
def parse_list(line):
    global max_players
    m=re.search(r"There are (\\d+) of a max of (\\d+) players online",line)
    if m:return int(m.group(1)),int(m.group(2))
    m=re.search(r"There are (\\d+) of a max (\\d+) players online",line)
    if m:return int(m.group(1)),int(m.group(2))
    return None

def metrics():
    m=psutil.virtual_memory();d=psutil.disk_usage(str(SERVER));return {"cpu":psutil.cpu_percent(),"ram_used_mb":round(m.used/1048576),"ram_total_mb":round(m.total/1048576),"disk_used_gb":round(d.used/1073741824,2),"disk_total_gb":round(d.total/1073741824,2),"minecraft_running":bool(process and process.poll() is None),"players_online":len(players),"players":sorted(players),"max_players":max_players}
async def output(ws):
    while True:
        if process and process.stdout:
            line=await asyncio.to_thread(process.stdout.readline)
            if line:parse_player(line);await send(ws,{"type":"log","line":line.rstrip(),"players_online":len(players)})
            else:await asyncio.sleep(.1)
        else:await asyncio.sleep(.5)
async def metrics_loop(ws):
    while True:
        if process and process.poll() is None:
            try: command("list")
            except Exception: pass
        await send(ws,{"type":"metrics","data":metrics()})
        await asyncio.sleep(5)
async def handle(ws,m):
    t=m.get("type")
    if t=="power":
        a=m.get("action")
        if a=="start":launch()
        elif a=="stop":stop()
        elif a=="restart":stop();time.sleep(2);launch()
        await send(ws,{"type":"ack","action":a})
    elif t=="command":command(m["command"]);await send(ws,{"type":"ack","command":m["command"]})
    elif t=="install":
        was=bool(process and process.poll() is None)
        if was:stop()
        try:
            await send(ws,{"type":"install","status":"backup","name":m.get("name")});await asyncio.to_thread(backup)
            await send(ws,{"type":"install","status":"download","name":m.get("name")});p=await asyncio.to_thread(download,m["url"],m.get("target","mods"))
            await send(ws,{"type":"install","status":"installed","name":m.get("name"),"path":p})
        finally:
            if was:launch()
    elif t=="files":
        action=m.get("action");rel=m.get("path","");p=safe(rel)
        if action=="list":
            if not p.exists():raise ValueError("Path not found")
            if not p.is_dir():raise ValueError("Not a directory")
            items=[{"name":x.name,"path":str(x.relative_to(SERVER)),"directory":x.is_dir(),"size":x.stat().st_size if x.is_file() else None} for x in sorted(p.iterdir(),key=lambda x:(not x.is_dir(),x.name.lower()))]
            await send(ws,{"type":"files","request_id":m.get("request_id"),"action":"list","items":items})
        elif action=="read":
            if not p.is_file() or p.stat().st_size>2000000:raise ValueError("File unavailable or too large")
            await send(ws,{"type":"files","request_id":m.get("request_id"),"action":"read","path":rel,"content":p.read_text(errors="strict")})
        elif action=="write":
            if p.name not in {"server.properties","whitelist.json","ops.json","eula.txt"}:raise ValueError("File is not editable")
            p.parent.mkdir(parents=True,exist_ok=True);p.write_text(m.get("content",""));await send(ws,{"type":"files","request_id":m.get("request_id"),"action":"write","ok":True})
        elif action=="delete":
            if p.name=="server.jar" or p.is_dir():raise ValueError("Deletion denied")
            p.unlink(missing_ok=True);await send(ws,{"type":"files","request_id":m.get("request_id"),"action":"delete","ok":True})
async def receive(ws):
    async for raw in ws:
        try:await handle(ws,json.loads(raw))
        except Exception as e:await send(ws,{"type":"error","message":str(e)})
async def run():
    while True:
        try:
            async with websockets.connect(URL,ping_interval=20,ping_timeout=20,max_size=4000000) as ws:
                launch();await send(ws,{"type":"hello","data":metrics()});await asyncio.gather(output(ws),metrics_loop(ws),receive(ws))
        except Exception as e:print("[agent] reconnect",e,flush=True);await asyncio.sleep(5)
if __name__=="__main__":asyncio.run(run())
