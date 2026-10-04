from __future__ import annotations
import asyncio,hmac,json,secrets,uuid
from datetime import datetime,timezone
from fastapi import Depends,FastAPI,Header,HTTPException,Query,WebSocket,WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel,Field
from .compute import create_vm,delete_vm,resolve_jar_url,vm_action
from .config import settings
from .providers import curseforge_file,curseforge_search,modrinth_search,modrinth_version
from .store import store
app=FastAPI(title=settings.app_name,version="1.0.0")
app.add_middleware(CORSMiddleware,allow_origins=settings.cors_list or ["*"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
AGENTS={};BROWSERS={}
def now():return datetime.now(timezone.utc).isoformat()
def valid(t):return bool(t and settings.admin_token and hmac.compare_digest(t,settings.admin_token))
def user(authorization: str|None=Header(default=None),x_minehub_token: str|None=Header(default=None)):
    t=x_minehub_token or (authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else None)
    if valid(t):return "admin"
    raise HTTPException(401,"Valid MineHub token required")
class CreateServer(BaseModel):
    name:str=Field(min_length=1,max_length=50);region:str="asia-south1";software:str="paper";mc_version:str="1.21.10";memory_mb:int=Field(default=2048,ge=1024,le=8192);public:bool=False
class InstallRequest(BaseModel):
    provider:str;project_id:str;loader:str="fabric";type:str="mod"
@app.get("/healthz")
async def healthz():return {"ok":True,"persistent_store":store.persistent,"time":now()}
@app.post("/api/auth/check")
async def auth_check(_=Depends(user)):return {"ok":True,"user":"admin"}
@app.get("/api/servers")
async def servers(_=Depends(user)):return {"servers":store.list_servers(owner_id="admin")}
@app.get("/api/public/servers")
async def public_servers():return {"servers":[{k:v for k,v in s.items() if k not in {"agent_token","owner_id"}} for s in store.list_servers(public_only=True)]}
@app.post("/api/servers")
async def create(body:CreateServer,_=Depends(user)):
    sw=body.software.lower()
    if sw not in {"paper","fabric","vanilla"}:raise HTTPException(400,"Supported runtime: Paper, Fabric, Vanilla")
    sid=uuid.uuid4().hex
    s={"id":sid,"owner_id":"admin","name":body.name,"region":body.region,"software":sw,"mc_version":body.mc_version,"memory_mb":body.memory_mb,"public":body.public,"status":"provisioning","vm_name":f"minehub-{sid[:12]}","agent_token":secrets.token_urlsafe(32),"created_at":now(),"players_online":0,"metrics":{},"game_address":None}
    store.put_server(s)
    try:
        u=await resolve_jar_url(sw,body.mc_version);info=await asyncio.to_thread(create_vm,s,u);s.update(info,status="starting");store.put_server(s);return {"server":{k:v for k,v in s.items() if k!="agent_token"}}
    except Exception as e:
        store.update_server(sid,status="error",error=str(e));raise HTTPException(502,f"VM provisioning failed: {e}")
@app.get("/api/servers/{sid}")
async def get(sid,_=Depends(user)):
    s=store.get_server(sid)
    if not s:raise HTTPException(404,"Server not found")
    return {"server":{k:v for k,v in s.items() if k!="agent_token"}}
@app.post("/api/servers/{sid}/power/{action}")
async def power(sid,action,_=Depends(user)):
    s=store.get_server(sid)
    if not s:raise HTTPException(404,"Server not found")
    if action not in {"start","stop","restart"}:raise HTTPException(400,"Invalid action")
    a=AGENTS.get(sid)
    if a:await a.send_json({"type":"power","action":action})
    else:await asyncio.to_thread(vm_action,s["vm_name"],"reset" if action=="restart" else action)
    store.update_server(sid,status={"start":"starting","stop":"stopping","restart":"restarting"}[action]);return {"ok":True}
@app.delete("/api/servers/{sid}")
async def remove(sid,_=Depends(user)):
    s=store.get_server(sid)
    if not s:raise HTTPException(404,"Server not found")
    await asyncio.to_thread(delete_vm,s["vm_name"]);store.delete_server(sid);return {"ok":True}
@app.get("/api/servers/{sid}/stats")
async def stats(sid,_=Depends(user)):
    s=store.get_server(sid)
    if not s:raise HTTPException(404,"Server not found")
    return {"metrics":s.get("metrics",{}),"players_online":s.get("players_online",0),"status":s.get("status")}
@app.get("/api/catalog/search")
async def catalog(q:str=Query(""),provider:str="modrinth",mc:str="1.21.10",loader:str="fabric",type:str="mod",_=Depends(user)):
    if provider=="modrinth":return {"items":await modrinth_search(q,mc,loader,type)}
    if provider=="curseforge":return {"items":await curseforge_search(q,mc,loader,type)}
    raise HTTPException(400,"Invalid provider")
@app.post("/api/servers/{sid}/install")
async def install(sid,body:InstallRequest,_=Depends(user)):
    s=store.get_server(sid)
    if not s:raise HTTPException(404,"Server not found")
    if body.provider=="modrinth":
        v=await modrinth_version(body.project_id,s["mc_version"],body.loader);f=next((x for x in v.get("files",[]) if x.get("primary")),v.get("files",[None])[0])
        if not f:raise HTTPException(404,"No download")
        p={"url":f["url"],"name":v["name"],"target":"plugins" if body.type=="plugin" else "mods"}
    elif body.provider=="curseforge":
        f=await curseforge_file(int(body.project_id),s["mc_version"],body.loader);p={"url":f["downloadUrl"],"name":f["displayName"],"target":"mods"}
    else:raise HTTPException(400,"Invalid provider")
    a=AGENTS.get(sid)
    if not a:raise HTTPException(409,"Runtime agent is offline")
    await a.send_json({"type":"install",**p});return {"ok":True,"queued":p["name"]}
@app.websocket("/agent/ws")
async def agent(ws:WebSocket,server_id:str,token:str):
    s=store.get_server(server_id)
    if not s or not hmac.compare_digest(str(s.get("agent_token","")),token):await ws.close(code=4401);return
    await ws.accept();AGENTS[server_id]=ws;store.update_server(server_id,status="online");BROWSERS.setdefault(server_id,set())
    try:
        async for raw in ws.iter_text():
            m=json.loads(raw);t=m.get("type")
            if t=="hello":store.update_server(server_id,metrics=m.get("data",{}),status="online")
            elif t=="metrics":store.update_server(server_id,metrics=m.get("data",{}),status="online" if m.get("data",{}).get("minecraft_running") else "offline")
            elif t in {"log","install"}:await broadcast(server_id,m)
    except WebSocketDisconnect:pass
    finally:
        if AGENTS.get(server_id) is ws:AGENTS.pop(server_id,None)
@app.websocket("/api/servers/{sid}/console")
async def console(ws:WebSocket,sid:str,token:str):
    s=store.get_server(sid)
    if not s or not valid(token):await ws.close(code=4401);return
    await ws.accept();BROWSERS.setdefault(sid,set()).add(ws)
    try:
        while True:
            m=await ws.receive_json();a=AGENTS.get(sid)
            if not a:await ws.send_json({"type":"error","message":"Runtime agent offline"});continue
            await a.send_json(m)
    except WebSocketDisconnect:pass
    finally:BROWSERS.get(sid,set()).discard(ws)
async def broadcast(sid,payload):
    dead=[]
    for ws in BROWSERS.get(sid,set()):
        try:await ws.send_json(payload)
        except Exception:dead.append(ws)
    for ws in dead:BROWSERS.get(sid,set()).discard(ws)
