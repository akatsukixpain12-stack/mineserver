from __future__ import annotations
import asyncio,json,re,shutil,time,urllib.request,subprocess,zipfile,hashlib,os
from pathlib import Path
import psutil,websockets

ROOT=Path("/opt/mineserver")
SERVER=ROOT/"server"
C=json.loads((ROOT/"config.json").read_text())
SERVER_ID=str(C.get("server_id") or "")
BASE=C["control_url"].rstrip("/")
URL=BASE.replace("https://","wss://").replace("http://","ws://")+"/agent/ws"
TOKEN=str(C.get("agent_token") or "")
BACKUP_BUCKET=str(C.get("backup_bucket") or "")
process=None
players=set()
max_players=20
lock=asyncio.Lock()
MEM=int(C.get("memory_mb") or max(1024,int((psutil.virtual_memory().total//1048576)*.75)))
RUNTIME=str(C.get("runtime") or "vanilla").lower()
JAVA_BIN=shutil.which("java") or "/usr/bin/java"

def safe(rel):
    p=(SERVER/rel.strip().replace("\\","/")).resolve()
    if p!=SERVER and SERVER not in p.parents:
        raise ValueError("Invalid path")
    return p

async def send(ws,x):
    async with lock:
        await ws.send(json.dumps(x))

def launch():
    global process
    if process and process.poll() is None:
        return
    if RUNTIME=="mineserver":
        binary=SERVER/"mineserver"
        if not binary.exists():
            raise RuntimeError("Mineserver native binary is missing")
        cmd=[str(binary)]
    elif RUNTIME in {"forge","neoforge"} and (SERVER/"run.sh").exists():
        cmd=["bash","run.sh"]
    else:
        jar=SERVER/"server.jar"
        if not jar.exists():
            raise RuntimeError(f"server.jar is missing for runtime {RUNTIME}")
        cmd=[JAVA_BIN,f"-Xms{max(512,MEM//2)}M",f"-Xmx{MEM}M","-jar",str(jar),"nogui"]
    env=os.environ.copy()
    env["JAVA_HOME"]=str(Path(JAVA_BIN).parent.parent)
    env["PATH"]=str(Path(JAVA_BIN).parent)+":"+env.get("PATH","")
    process=subprocess.Popen(
        cmd,cwd=SERVER,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,text=True,bufsize=1
    )

def stop():
    global process
    if not process or process.poll() is not None:
        process=None
        return
    try:
        process.stdin.write("stop\n")
        process.stdin.flush()
        process.wait(timeout=30)
    except Exception:
        try: process.kill()
        except Exception: pass
    process=None

def command(x):
    if not process or process.poll() is not None:
        raise RuntimeError("Minecraft is not running")
    process.stdin.write(x.lstrip("/")+"\n")
    process.stdin.flush()

def backup():
    b=ROOT/"backups"
    b.mkdir(exist_ok=True)
    name="backup-"+time.strftime("%Y%m%d-%H%M%S")
    archive=Path(shutil.make_archive(str(b/name),"zip",root_dir=SERVER))
    if not BACKUP_BUCKET:
        return {"local_path":str(archive),"uri":None}
    from google.cloud import storage
    client=storage.Client()
    object_name=f"servers/{SERVER_ID}/{archive.name}"
    blob=client.bucket(BACKUP_BUCKET).blob(object_name)
    blob.upload_from_filename(str(archive),content_type="application/zip")
    return {"local_path":str(archive),"uri":f"gs://{BACKUP_BUCKET}/{object_name}","object":object_name,"size":archive.stat().st_size}

def download_zip_pack(url):
    tmp=ROOT/"serverpack.tmp.zip"
    req=urllib.request.Request(url,headers={"User-Agent":"Mineserver-Agent/3.0"})
    with urllib.request.urlopen(req,timeout=180) as r,open(tmp,"wb") as f:
        shutil.copyfileobj(r,f)
    if not zipfile.is_zipfile(tmp):
        raise ValueError("Server pack is not a valid ZIP")
    with zipfile.ZipFile(tmp) as z:
        for info in z.infolist():
            rel=info.filename.replace("\\","/")
            if rel.endswith("/") or rel.startswith("/") or ".." in Path(rel).parts:
                continue
            dest=safe(rel)
            dest.parent.mkdir(parents=True,exist_ok=True)
            with z.open(info) as src,open(dest,"wb") as dst:
                shutil.copyfileobj(src,dst)
    tmp.unlink(missing_ok=True)
    return "server pack"

def download_modpack(url):
    tmp=ROOT/"modpack.tmp.mrpack"
    req=urllib.request.Request(url,headers={"User-Agent":"Mineserver-Agent/3.0"})
    with urllib.request.urlopen(req,timeout=180) as r,open(tmp,"wb") as f:
        shutil.copyfileobj(r,f)
    if not zipfile.is_zipfile(tmp):
        raise ValueError("Downloaded modpack is not a valid ZIP/.mrpack")
    with zipfile.ZipFile(tmp) as z:
        names=set(z.namelist())
        if "modrinth.index.json" not in names:
            raise ValueError("Only Modrinth .mrpack server installs are supported")
        index=json.loads(z.read("modrinth.index.json").decode("utf-8"))
        if index.get("formatVersion")!=1 or index.get("game")!="minecraft":
            raise ValueError("Unsupported Modrinth pack format")
        for item in index.get("files",[]):
            if item.get("env",{}).get("server")=="unsupported":
                continue
            rel=item.get("path","").replace("\\","/")
            dest=safe(rel)
            if dest==SERVER or rel.startswith("/") or ".." in Path(rel).parts:
                raise ValueError("Unsafe modpack path")
            urls=item.get("downloads",[])
            if not urls:
                raise ValueError("Modpack entry has no download URL: "+rel)
            dest.parent.mkdir(parents=True,exist_ok=True)
            part=dest.with_suffix(dest.suffix+".part")
            req2=urllib.request.Request(urls[0],headers={"User-Agent":"Mineserver-Agent/3.0"})
            with urllib.request.urlopen(req2,timeout=120) as r,open(part,"wb") as f:
                shutil.copyfileobj(r,f)
            hashes=item.get("hashes",{})
            expected=hashes.get("sha512") or hashes.get("sha1")
            if expected:
                h=hashlib.sha512() if hashes.get("sha512") else hashlib.sha1()
                with open(part,"rb") as rf:
                    for chunk in iter(lambda:rf.read(1024*1024),b""):
                        h.update(chunk)
                if h.hexdigest().lower()!=expected.lower():
                    part.unlink(missing_ok=True)
                    raise ValueError("Hash mismatch for "+rel)
            part.replace(dest)
        for root in ("overrides","server-overrides"):
            prefix=root+"/"
            for name in names:
                if not name.startswith(prefix) or name.endswith("/"):
                    continue
                rel=name[len(prefix):]
                dest=safe(rel)
                dest.parent.mkdir(parents=True,exist_ok=True)
                with z.open(name) as src,open(dest,"wb") as dst:
                    shutil.copyfileobj(src,dst)
    tmp.unlink(missing_ok=True)
    return index.get("name","Modrinth modpack")

def download(url,target):
    folder=safe(target)
    folder.mkdir(parents=True,exist_ok=True)
    name=url.split("?")[0].rsplit("/",1)[-1] or "download.jar"
    out=folder/name
    tmp=out.with_suffix(out.suffix+".part")
    req=urllib.request.Request(url,headers={"User-Agent":"Mineserver-Agent/3.0"})
    with urllib.request.urlopen(req,timeout=120) as r,open(tmp,"wb") as f:
        shutil.copyfileobj(r,f)
    tmp.replace(out)
    return str(out.relative_to(SERVER))

def parse_player(line):
    m=re.search(r"([A-Za-z0-9_]{1,16}) joined the game",line)
    if m: players.add(m.group(1))
    m=re.search(r"([A-Za-z0-9_]{1,16}) left the game",line)
    if m: players.discard(m.group(1))

def parse_list(line):
    global max_players
    m=re.search(r"There are (\d+) of a max of (\d+) players online",line)
    if m:
        return int(m.group(1)),int(m.group(2))
    m=re.search(r"There are (\d+) of a max (\d+) players online",line)
    if m:
        return int(m.group(1)),int(m.group(2))
    return None

def metrics():
    m=psutil.virtual_memory()
    d=psutil.disk_usage(str(SERVER))
    running=bool(process and process.poll() is None)
    return {
        "cpu":psutil.cpu_percent(),
        "ram_used_mb":round(m.used/1048576),
        "ram_total_mb":round(m.total/1048576),
        "disk_used_gb":round(d.used/1073741824),
        "disk_total_gb":round(d.total/1073741824),
        "players":sorted(players),
        "players_online":len(players),
        "max_players":max_players,
        "minecraft_running":running,
    }

async def output(ws):
    while True:
        if process and process.stdout:
            line=await asyncio.to_thread(process.stdout.readline)
            if line:
                parse_player(line)
                parsed=parse_list(line)
                if parsed:
                    globals()["max_players"]=parsed[1]
                await send(ws,{"type":"log","line":line.rstrip(),"players":sorted(players),"players_online":len(players),"max_players":max_players})
            else:
                await asyncio.sleep(.1)
        else:
            await asyncio.sleep(.5)

async def metrics_loop(ws):
    while True:
        if process and process.poll() is None and RUNTIME!="mineserver":
            try: command("list")
            except Exception: pass
        await send(ws,{"type":"metrics","data":metrics()})
        await asyncio.sleep(5)

def list_files(rel=""):
    p=(SERVER/rel).resolve()
    if SERVER not in p.parents and p!=SERVER:
        raise ValueError("Invalid path")
    if not p.is_dir():
        raise ValueError("Not a directory")
    return [
        {"name":x.name,"path":str(x.relative_to(SERVER)),"directory":x.is_dir(),"size":x.stat().st_size if x.is_file() else None}
        for x in sorted(p.iterdir(),key=lambda x:(not x.is_dir(),x.name.lower()))
    ]

def read_text(rel):
    p=(SERVER/rel).resolve()
    if SERVER not in p.parents or not p.is_file():
        raise ValueError("Invalid file")
    if p.stat().st_size>2000000:
        raise ValueError("File too large")
    return p.read_text()

def write_text(rel,content):
    p=(SERVER/rel).resolve()
    if SERVER not in p.parents or p==SERVER:
        raise ValueError("Invalid file")
    allowed={"server.properties","eula.txt","whitelist.json","ops.json","banned-players.json","banned-ips.json"}
    if p.name not in allowed and not str(p).startswith(str(SERVER/"config")):
        raise ValueError("File is not editable")
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(content)

async def handle(ws,m):
    t=m.get("type")
    if t=="power":
        a=m.get("action")
        if a=="start":
            launch()
        elif a=="stop":
            stop()
        elif a=="restart":
            stop()
            await asyncio.sleep(2)
            launch()
        else:
            raise ValueError("Invalid power action")
        await send(ws,{"type":"ack","action":a})
    elif t=="command":
        command(m["command"])
        await send(ws,{"type":"ack","command":m["command"]})
    elif t=="files_list":
        try:
            await send(ws,{"type":"files","action":"list","path":m.get("path",""),"items":list_files(m.get("path",""))})
        except Exception as exc:
            await send(ws,{"type":"files","action":"error","message":str(exc)})
    elif t=="file_read":
        try:
            await send(ws,{"type":"files","action":"read","path":m["path"],"content":read_text(m["path"])})
        except Exception as exc:
            await send(ws,{"type":"files","action":"error","message":str(exc)})
    elif t=="file_write":
        try:
            write_text(m["path"],m["content"])
            await send(ws,{"type":"files","action":"saved","path":m["path"]})
        except Exception as exc:
            await send(ws,{"type":"files","action":"error","message":str(exc)})
    elif t=="backup":
        try:
            await send(ws,{"type":"backup","status":"creating"})
            result=await asyncio.to_thread(backup)
            await send(ws,{"type":"backup","status":"uploaded" if result.get("uri") else "local","name":Path(result["local_path"]).name,**result})
        except Exception as exc:
            await send(ws,{"type":"backup","status":"error","message":str(exc)})
    elif t=="install":
        was_running=bool(process and process.poll() is None)
        if was_running:
            stop()
        try:
            await send(ws,{"type":"install","status":"backup","name":m.get("name")})
            await asyncio.to_thread(backup)
            await send(ws,{"type":"install","status":"download","name":m.get("name")})
            if m.get("target")=="modpack-zip":
                result=await asyncio.to_thread(download_zip_pack,m["url"])
            elif m.get("target")=="modpack":
                result=await asyncio.to_thread(download_modpack,m["url"])
            else:
                result=await asyncio.to_thread(download,m["url"],m.get("target","mods"))
            await send(ws,{"type":"install","status":"installed","name":m.get("name"),"path":result})
        except Exception as exc:
            await send(ws,{"type":"install","status":"error","name":m.get("name"),"message":str(exc)})
        finally:
            if was_running:
                launch()
    elif t=="files":
        action=m.get("action")
        rel=m.get("path","")
        p=safe(rel)
        if action=="list":
            if not p.exists() or not p.is_dir():
                raise ValueError("Path unavailable")
            items=[
                {"name":x.name,"path":str(x.relative_to(SERVER)),"directory":x.is_dir(),"size":x.stat().st_size if x.is_file() else None}
                for x in sorted(p.iterdir(),key=lambda x:(not x.is_dir(),x.name.lower()))
            ]
            await send(ws,{"type":"files","request_id":m.get("request_id"),"action":"list","items":items,"path":rel})
        elif action=="read":
            if not p.is_file() or p.stat().st_size>2000000:
                raise ValueError("File unavailable or too large")
            await send(ws,{"type":"files","request_id":m.get("request_id"),"action":"read","path":rel,"content":p.read_text(errors="strict")})
        elif action=="write":
            write_text(rel,m.get("content",""))
            await send(ws,{"type":"files","request_id":m.get("request_id"),"action":"saved","path":rel})
        elif action=="delete":
            if p.name in {"server.jar","mineserver"} or p.is_dir():
                raise ValueError("Deletion denied")
            p.unlink(missing_ok=True)
            await send(ws,{"type":"files","request_id":m.get("request_id"),"action":"delete","path":rel})

async def receive(ws):
    async for raw in ws:
        try:
            await handle(ws,json.loads(raw))
        except Exception as exc:
            await send(ws,{"type":"error","message":str(exc)})

async def run():
    while True:
        try:
            async with websockets.connect(
                f"{URL}?server_id={SERVER_ID}&token={TOKEN}",
                ping_interval=20,ping_timeout=20,max_size=4000000
            ) as ws:
                launch()
                await send(ws,{"type":"hello","data":metrics()})
                await asyncio.gather(output(ws),metrics_loop(ws),receive(ws))
        except Exception as exc:
            print("[mineserver-agent] reconnect",exc,flush=True)
            await asyncio.sleep(5)

if __name__=="__main__":
    asyncio.run(run())