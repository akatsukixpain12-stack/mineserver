from __future__ import annotations
import asyncio,hmac,json,secrets,uuid
from datetime import datetime,timezone
from pathlib import Path
from fastapi import Depends,FastAPI,Header,HTTPException,Query,WebSocket,WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from pydantic import BaseModel,Field
from .compute import create_vm,delete_vm,resolve_jar_url,vm_action
from .runtime import RUNTIMES,catalog as runtime_catalog,versions_for as runtime_versions
from .config import settings
from .providers import curseforge_file,curseforge_search,modrinth_search,modrinth_version
from .store import store

app=FastAPI(title=settings.app_name,version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=False,
    allow_methods=["GET","POST","DELETE","OPTIONS"],
    allow_headers=["Authorization","Content-Type","Accept"],
)
AGENTS={}
BROWSERS={}

def now():
    return datetime.now(timezone.utc).isoformat()

def verify_google_id_token(raw_token:str):
    if not settings.google_client_id:
        raise HTTPException(503,"Google login is not configured by the administrator.")
    try:
        payload=id_token.verify_oauth2_token(
            raw_token,
            google_requests.Request(),
            settings.google_client_id,
        )
    except Exception as exc:
        raise HTTPException(401,"Invalid or expired Google login token") from exc
    if payload.get("iss") not in {"accounts.google.com","https://accounts.google.com"}:
        raise HTTPException(401,"Invalid Google token issuer")
    if str(payload.get("aud") or "") != settings.google_client_id:
        raise HTTPException(401,"Invalid Google token audience")
    sub=str(payload.get("sub") or "").strip()
    if not sub:
        raise HTTPException(401,"Google token has no account subject")
    return {
        "id":sub,
        "name":str(payload.get("name") or payload.get("email") or "Google user"),
        "email":str(payload.get("email") or ""),
        "picture":str(payload.get("picture") or ""),
    }

def workspace(authorization:str|None=Header(default=None)):
    value=(authorization or "").strip()
    if not value.lower().startswith("bearer "):
        raise HTTPException(401,"Sign in with Google is required.")
    user=verify_google_id_token(value[7:].strip())
    store.upsert_user(user)
    return user

def user(u=Depends(workspace)):
    return u

def owns(s,user):
    if not s or s.get("owner_id")!=user["id"]:
        raise HTTPException(404,"Server not found")

class CreateServer(BaseModel):
    name:str=Field(min_length=1,max_length=50)
    region:str="asia-south1"
    software:str="paper"
    mc_version:str=""
    memory_mb:int=Field(default=2048,ge=1024,le=16384)
    disk_gb:int=Field(default=20,ge=10,le=500)
    public:bool=False

class InstallRequest(BaseModel):
    provider:str
    project_id:str
    loader:str=""
    type:str="mod"

VALID_REGIONS={
    "asia-south1":"asia-south1-a",
    "asia-southeast1":"asia-southeast1-a",
    "us-central1":"us-central1-a",
    "europe-west1":"europe-west1-b",
}

@app.get("/healthz")
async def healthz():
    return {"ok":True,"persistent_store":store.persistent,"time":now()}

@app.get("/api/config")
async def public_config():
    return {
        "app_name":settings.app_name,
        "auth":"google",
        "google_client_id":settings.google_client_id,
        "google_configured":bool(settings.google_client_id),
        "web_control_plane":True,
        "same_origin":True,
    }

@app.post("/api/auth/check")
async def auth_check(u=Depends(user)):
    return {"ok":True,"user":u}

@app.get("/api/servers")
async def servers(u=Depends(user)):
    items=[]
    for s in store.list_servers(owner_id=u["id"]):
        items.append({k:v for k,v in s.items() if k!="agent_token"})
    return {"servers":items,"user":u}

@app.get("/api/public/servers")
async def public_servers():
    fields={"agent_token","owner_id","error","control_token","vm_id"}
    return {
        "servers":[
            {k:v for k,v in s.items() if k not in fields}
            for s in store.list_servers(public_only=True)
        ]
    }

@app.post("/api/servers")
async def create(body:CreateServer,u=Depends(user)):
    sw=body.software.lower().strip()
    if sw not in {x["id"] for x in RUNTIMES}:
        raise HTTPException(400,"Unsupported Minecraft runtime")
    if body.region not in VALID_REGIONS:
        raise HTTPException(400,"Unsupported region")
    if not body.mc_version:
        versions=await runtime_versions(sw)
        if sw=="mineserver":
            body.mc_version=(versions.get(sw) or [{}])[0].get("id","")
        else:
            body.mc_version=(versions.get(sw) or [{}])[0].get("id","")
    if not body.mc_version:
        raise HTTPException(400,"No compatible version is available for this runtime")
    sid=uuid.uuid4().hex
    vm_name=f"ms-{sid[:18]}"
    s={
        "id":sid,
        "owner_id":u["id"],
        "name":body.name.strip(),
        "region":body.region,
        "zone":VALID_REGIONS[body.region],
        "software":sw,
        "mc_version":body.mc_version,
        "memory_mb":body.memory_mb,
        "disk_gb":body.disk_gb,
        "public":body.public,
        "status":"creating",
        "agent_token":secrets.token_urlsafe(32),
        "vm_name":vm_name,
        "vm_id":"",
        "public_ip":None,
        "game_address":None,
        "players_online":0,
        "players":[],
        "max_players":20,
        "metrics":{},
        "permissions":{u["id"]:"owner"},
        "created_at":now(),
        "last_activity":now(),
    }
    store.put_server(s)
    try:
        jar=await resolve_jar_url(sw,body.mc_version)
        info=await asyncio.to_thread(create_vm,s,jar)
        s.update(info,status="starting")
        store.put_server(s)
        return {"server":{k:v for k,v in s.items() if k!="agent_token"}}
    except Exception as exc:
        store.update_server(sid,status="error",error=str(exc),last_activity=now())
        raise HTTPException(502,f"VM provisioning failed: {exc}") from exc

@app.get("/api/servers/{sid}")
async def get_server(sid,u=Depends(user)):
    s=store.get_server(sid);owns(s,u)
    return {"server":{k:v for k,v in s.items() if k!="agent_token"}}

@app.post("/api/servers/{sid}/power/{action}")
async def power(sid,action,u=Depends(user)):
    s=store.get_server(sid);owns(s,u)
    if action not in {"start","stop","restart"}:
        raise HTTPException(400,"Invalid power action")
    a=AGENTS.get(sid)
    try:
        if a:
            await a.send_json({"type":"power","action":action})
        else:
            vm=s.get("vm_name")
            if not vm:
                raise RuntimeError("Runtime VM is not provisioned")
            await asyncio.to_thread(vm_action,vm,"reset" if action=="restart" else action,s.get("zone"))
        target={"start":"starting","stop":"stopping","restart":"restarting"}[action]
        store.update_server(sid,status=target,last_activity=now())
        return {"ok":True,"action":action}
    except Exception as exc:
        store.update_server(sid,status="error",error=str(exc),last_activity=now())
        raise HTTPException(502,f"Power action failed: {exc}") from exc

@app.delete("/api/servers/{sid}")
async def remove(sid,u=Depends(user)):
    s=store.get_server(sid);owns(s,u)
    vm=s.get("vm_name")
    if vm:
        await asyncio.to_thread(delete_vm,vm,s.get("zone"))
    store.delete_server(sid)
    return {"ok":True}

@app.get("/api/servers/{sid}/stats")
async def stats(sid,u=Depends(user)):
    s=store.get_server(sid);owns(s,u)
    return {
        "metrics":s.get("metrics",{}),
        "players_online":s.get("players_online",0),
        "players":s.get("players",[]),
        "max_players":s.get("max_players",20),
        "status":s.get("status"),
        "game_address":s.get("game_address"),
    }

@app.get("/api/servers/{sid}/files")
async def files(sid,path:str="",u=Depends(user)):
    s=store.get_server(sid);owns(s,u)
    if not AGENTS.get(sid):
        raise HTTPException(409,"Runtime agent is offline")
    await AGENTS[sid].send_json({"type":"files_list","path":path})
    return {"queued":True,"path":path}

@app.get("/api/catalog/runtimes")
async def runtimes():
    return {"runtimes":RUNTIMES}

@app.get("/api/catalog/versions")
async def versions(runtime:str|None=None):
    try:
        if runtime:
            return {"versions":await runtime_versions(runtime)}
        return {"versions":await runtime_catalog()}
    except Exception as exc:
        raise HTTPException(502,f"Version catalog unavailable: {exc}") from exc

@app.get("/api/catalog/search")
async def catalog(
    q:str=Query(""),
    provider:str="modrinth",
    mc:str="",
    loader:str="",
    type:str="mod",
    u=Depends(user),
):
    if not mc:
        raise HTTPException(400,"Minecraft version is required")
    if provider=="modrinth":
        return {"items":await modrinth_search(q,mc,loader,type)}
    if provider=="curseforge":
        return {"items":await curseforge_search(q,mc,loader,type)}
    raise HTTPException(400,"Invalid provider")

@app.get("/api/servers/{sid}/backups")
async def list_backups(sid,u=Depends(user)):
    s=store.get_server(sid);owns(s,u)
    if not settings.backup_bucket:
        return {"configured":False,"backups":[]}
    try:
        from google.cloud import storage
        client=storage.Client(project=settings.project_id or None)
        bucket=client.bucket(settings.backup_bucket)
        prefix=f"servers/{sid}/"
        rows=[]
        for blob in client.list_blobs(bucket, prefix=prefix):
            rows.append({"name":blob.name.rsplit("/",1)[-1],"object":blob.name,"size":blob.size or 0,"created_at":blob.time_created.isoformat() if blob.time_created else None,"updated_at":blob.updated.isoformat() if blob.updated else None,"uri":f"gs://{settings.backup_bucket}/{blob.name}"})
        rows.sort(key=lambda x:x.get("created_at") or "",reverse=True)
        return {"configured":True,"backups":rows[:100]}
    except Exception as exc:
        raise HTTPException(502,f"Backup storage unavailable: {exc}") from exc

@app.post("/api/servers/{sid}/backups")
async def create_backup(sid,u=Depends(user)):
    s=store.get_server(sid);owns(s,u)
    if not settings.backup_bucket:
        raise HTTPException(503,"Cloud backup storage is not configured.")
    agent=AGENTS.get(sid)
    if not agent:
        raise HTTPException(409,"Runtime agent is offline")
    await agent.send_json({"type":"backup"})
    return {"ok":True,"queued":True}

@app.post("/api/servers/{sid}/install")
async def install(sid,body:InstallRequest,u=Depends(user)):
    s=store.get_server(sid);owns(s,u)
    if body.provider=="modrinth":
        v=await modrinth_version(body.project_id,s["mc_version"],body.loader)
        f=next((x for x in v.get("files",[]) if x.get("primary")),v.get("files",[None])[0])
        if not f:
            raise HTTPException(404,"No compatible download")
        p={
            "url":f["url"],
            "name":v.get("name") or body.project_id,
            "target":"plugins" if body.type=="plugin" else ("modpack" if body.type=="modpack" else "mods"),
            "sha1":f.get("hashes",{}).get("sha1"),
        }
    elif body.provider=="curseforge":
        f=await curseforge_file(int(body.project_id),s["mc_version"],body.loader,body.type)
        p={
            "url":f["downloadUrl"],
            "name":f["displayName"],
            "target":"plugins" if body.type=="plugin" else ("modpack-zip" if body.type=="modpack" else "mods"),
        }
    else:
        raise HTTPException(400,"Invalid provider")
    a=AGENTS.get(sid)
    if not a:
        raise HTTPException(409,"Runtime agent is offline")
    await a.send_json({"type":"install",**p})
    store.update_server(sid,last_activity=now())
    return {"ok":True,"queued":p["name"]}

@app.websocket("/agent/ws")
async def agent(ws:WebSocket,server_id:str,token:str):
    s=store.get_server(server_id)
    if not s or not hmac.compare_digest(str(s.get("agent_token","")),token):
        await ws.close(code=4401);return
    await ws.accept()
    AGENTS[server_id]=ws
    try:
        async for raw in ws.iter_text():
            try:
                m=json.loads(raw)
            except json.JSONDecodeError:
                continue
            t=m.get("type")
            if t=="hello":
                data=m.get("data",{})
                store.update_server(
                    server_id,
                    metrics=data,
                    status="online" if data.get("minecraft_running") else "offline",
                    players_online=data.get("players_online",0),
                    players=data.get("players",[]),
                    max_players=data.get("max_players",20),
                    last_activity=now(),
                )
                await broadcast(server_id,{"type":"metrics","data":data})
            elif t=="metrics":
                data=m.get("data",{})
                store.update_server(
                    server_id,
                    metrics=data,
                    status="online" if data.get("minecraft_running") else "offline",
                    players_online=data.get("players_online",0),
                    players=data.get("players",[]),
                    max_players=data.get("max_players",20),
                    last_activity=now(),
                )
                await broadcast(server_id,m)
            elif t=="players":
                store.update_server(
                    server_id,
                    players_online=m.get("count",0),
                    players=m.get("players",[]),
                    max_players=m.get("max_players",20),
                    last_activity=now(),
                )
                await broadcast(server_id,m)
            elif t in {"log","install","files","error"}:
                await broadcast(server_id,m)
    except WebSocketDisconnect:
        pass
    finally:
        if AGENTS.get(server_id) is ws:
            AGENTS.pop(server_id,None)
        try:
            store.update_server(server_id,status="offline",last_activity=now())
            await broadcast(server_id,{"type":"runtime","status":"offline"})
        except Exception:
            pass

@app.websocket("/api/servers/{sid}/console")
async def console(ws:WebSocket,sid:str):
    s=store.get_server(sid)
    if not s:
        await ws.close(code=4404);return
    await ws.accept()
    try:
        auth=await ws.receive_json()
        if auth.get("type")!="auth":
            await ws.close(code=4401);return
        u=verify_google_id_token(str(auth.get("token") or ""))
        store.upsert_user(u)
        if s.get("owner_id")!=u["id"]:
            await ws.close(code=4404);return
        BROWSERS.setdefault(sid,set()).add(ws)
        await ws.send_json({"type":"runtime","status":s.get("status","offline")})
        while True:
            m=await ws.receive_json()
            a=AGENTS.get(sid)
            if not a:
                await ws.send_json({"type":"error","message":"Minecraft runtime agent is offline"})
                continue
            await a.send_json(m)
    except WebSocketDisconnect:
        pass
    finally:
        BROWSERS.get(sid,set()).discard(ws)

async def broadcast(sid,payload):
    dead=[]
    for ws in BROWSERS.get(sid,set()):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        BROWSERS.get(sid,set()).discard(ws)

# Cloud Run serves this exact frontend from the same origin as the API.
for candidate in (
    Path("/app/web"),
    Path(__file__).resolve().parents[2] / "web",
    Path.cwd() / "web",
):
    if candidate.is_dir():
        app.mount("/",StaticFiles(directory=str(candidate),html=True),name="web")
        break

@app.exception_handler(404)
async def not_found(_request,_exc):
    return JSONResponse({"detail":"Mineserver route not found"},status_code=404)