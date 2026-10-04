from __future__ import annotations
import asyncio,json,shutil,subprocess,time
from pathlib import Path
import psutil,websockets
ROOT=Path("/opt/minehub");SERVER=ROOT/"server";C=json.loads((ROOT/"config.json").read_text());BASE=C["control_url"].rstrip("/").replace("https://","wss://").replace("http://","ws://");URL=f"{BASE}/agent/ws?server_id={C['server_id']}&token={C['agent_token']}";MEM=int(C.get("memory_mb",2048));process=None;lock=asyncio.Lock()
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
def backup(path):
    b=ROOT/"backups";b.mkdir(exist_ok=True);shutil.make_archive(str(b/(path+"-"+time.strftime("%Y%m%d-%H%M%S"))),"zip",root_dir=SERVER,base_dir=path)
def download(url,target):
    import urllib.request
    folder=SERVER/target;folder.mkdir(parents=True,exist_ok=True);name=url.split("?")[0].rsplit("/",1)[-1] or "download.jar";out=folder/name;tmp=out.with_suffix(out.suffix+".part");req=urllib.request.Request(url,headers={"User-Agent":"MineHub-Agent/1.0"})
    with urllib.request.urlopen(req,timeout=90) as r,open(tmp,"wb") as f:shutil.copyfileobj(r,f)
    tmp.replace(out);return str(out)
def metrics():
    m=psutil.virtual_memory();d=psutil.disk_usage(str(SERVER));return {"cpu":psutil.cpu_percent(),"ram_used_mb":round(m.used/1048576),"ram_total_mb":round(m.total/1048576),"disk_used_gb":round(d.used/1073741824,2),"disk_total_gb":round(d.total/1073741824,2),"minecraft_running":bool(process and process.poll() is None)}
async def output(ws):
    while True:
        if process and process.stdout:
            line=await asyncio.to_thread(process.stdout.readline)
            if line:await send(ws,{"type":"log","line":line.rstrip()})
            else:await asyncio.sleep(.1)
        else:await asyncio.sleep(.5)
async def metrics_loop(ws):
    while True:await send(ws,{"type":"metrics","data":metrics()});await asyncio.sleep(3)
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
            await send(ws,{"type":"install","status":"backup","name":m.get("name")});await asyncio.to_thread(backup,m.get("target","mods"));await send(ws,{"type":"install","status":"download","name":m.get("name")});p=await asyncio.to_thread(download,m["url"],m.get("target","mods"));await send(ws,{"type":"install","status":"installed","name":m.get("name"),"path":p})
        finally:
            if was:launch()
async def receive(ws):
    async for raw in ws:await handle(ws,json.loads(raw))
async def run():
    while True:
        try:
            async with websockets.connect(URL,ping_interval=20,ping_timeout=20,max_size=4000000) as ws:await send(ws,{"type":"hello","data":metrics()});await asyncio.gather(output(ws),metrics_loop(ws),receive(ws))
        except Exception as e:print("[agent] reconnect",e,flush=True);await asyncio.sleep(5)
if __name__=="__main__":asyncio.run(run())
