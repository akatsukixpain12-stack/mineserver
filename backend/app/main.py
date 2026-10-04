from __future__ import annotations
import asyncio,hmac,json,secrets,uuid
from datetime import datetime,timezone
from fastapi import Depends,FastAPI,Header,HTTPException,Query,WebSocket,WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from pydantic import BaseModel,Field
from .compute import create_vm,delete_vm,resolve_jar_url,vm_action
from .runtime import RUNTIMES,catalog as runtime_catalog
from .config import settings
from .providers import curseforge_file,curseforge_search,modrinth_search,modrinth_version
from .store import store

app=FastAPI(title=settings.app_name,version="2.0.0")
app.add_middleware(CORSMiddleware,allow_origins=settings.cors_list or ["*"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
AGENTS={};BROWSERS={}

def now(): return datetime.now(timezone.utc).isoformat()

def google_user(authorization: str|None):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401,"Sign in with Google first")
    token=authorization[7:].strip()
    try:
        claims=id_token.verify_oauth2_token(token,google_requests.Request(),audience=settings.google_client_id)
    except Exception as e:
        raise HTTPException(401,"Invalid Google sign-in token") from e
    if claims.get("iss") not in {"accounts.google.com","https://accounts.google.com"}:
        raise HTTPException(401,"Invalid Google token issuer")
    if not claims.get("sub") or not claims.get("email"):
        raise HTTPException(401,"Google account information is incomplete")
    return {"id":claims["sub"],"email":claims["email"],"name":claims.get("name") or claims["email"].split("@")[0],"picture":claims.get("picture","")}

def user(authorization: str|None=Header(default=None)): return google_user(authorization)

def owns(s,user):
    if not s or s.get("owner_id")!=user["id"]: raise HTTPException(404,"Server not found")

class CreateServer(BaseModel):
    name:str=Field(min_length=1,max_length=50)
    region:str="asia-south1"
    software:str="paper"
    mc_version:str="1.21.10"
    memory_mb:int=Field(default=2048,ge=1024,le=8192)
    public:bool=False

class InstallRequest(BaseModel):
    provider:str
    project_id:str
    loader:str="fabric"
    type:str="mod"

@app.get("/healthz")
async def healthz(): return {"ok":True,"persistent_store":store.persistent,"time":now()}

@app.get("/api/config")
async def public_config():
    return {"google_client_id":settings.google_client_id,"app_name":settings.app_name}

@app.post("/api/auth/check")
async def auth_check(u=Depends(user)): return {"ok":True,"user":u}

@app.get("/api/servers")
async def servers(u=Depends(user)):
    items=[]
    for s in store.list_servers(owner_id=u["id"]):
        items.append({k:v for k,v in s.items() if k!="agent_token"})
    return {"servers":items,"user":u}

@app.get("/api/public/servers")
async def public_servers():
    fields={"agent_token","owner_id"}
    return {"servers":[{k:v for k,v in s.items() if k not in fields} for s in store.list_servers(public_only=True)]}

@app.post("/api/servers")
async def create(body:CreateServer,u=Depends(user)):
    sw=body.software.lower()
    if sw not in {x["id"] for x in RUNTIMES}: raise HTTPException(400,"Unsupported Minecraft runtime")
    sid=uuid.uuid4().hex
    s={"id":sid,"owner_id":u["id"],"owner_email":u["email"],"owner_name":u["name"],"name":body.name,"region":body.region,"zone":{"asia-south1":"asia-south1-a","asia-southeast1":"asia-southeast1-a","us-central1":"us-central1-a","europe-west1":"europe-west1-b"}.get(body.region,settings.compute_zone),"software":sw,"mc_version":body.mc_version,"memory_mb":body.memory_mb,"public":body.public,"status":"provisioning","vm_name":f"minehub-{sid[:12]}","agent_token":secrets.token_urlsafe(32),"created_at":now(),"players_online":0,"players":[],"max_players":20,"metrics":{},"game_address":None}
    store.put_server(s)
    try:
        jar=await resolve_jar_url(sw,body.mc_version)
        info=await asyncio.to_thread(create_vm,s,jar)
        s.update(info,status="starting");store.put_server(s)
        return {"server":{k:v for k,v in s.items() if k!="agent_token"}}
    except Exception as e:
        store.update_server(sid,status="error",error=str(e))
        raise HTTPException(502,f"VM provisioning failed: {e}")

@app.get("/api/servers/{sid}")
async def get_server(sid,u=Depends(user)):
    s=store.get_server(sid);owns(s,u)
    return {"server":{k:v for k,v in s.items() if k!="agent_token"}}

@app.post("/api/servers/{sid}/power/{action}")
async def power(sid,action,u=Depends(user)):
    s=store.get_server(sid);owns(s,u)
    if action not in {"start","stop","restart"}: raise HTTPException(400,"Invalid action")
    a=AGENTS.get(sid)
    if a:
        await a.send_json({"type":"power","action":action})
    else:
        await asyncio.to_thread(vm_action,s["vm_name"],"reset" if action=="restart" else action,s.get("zone"))
    store.update_server(sid,status={"start":"starting","stop":"stopping","restart":"restarting"}[action])
    return {"ok":True,"action":action}

@app.delete("/api/servers/{sid}")
async def remove(sid,u=Depends(user)):
    s=store.get_server(sid);owns(s,u)
    await asyncio.to_thread(delete_vm,s["vm_name"],s.get("zone"));store.delete_server(sid)
    return {"ok":True}

@app.get("/api/servers/{sid}/stats")
async def stats(sid,u=Depends(user)):
    s=store.get_server(sid);owns(s,u)
    return {"metrics":s.get("metrics",{}),"players_online":s.get("players_online",0),"players":s.get("players",[]),"max_players":s.get("max_players",20),"status":s.get("status")}

@app.get("/api/servers/{sid}/files")
async def files(sid,path:str="",u=Depends(user)):
    s=store.get_server(sid);owns(s,u)
    a=AGENTS.get(sid)
    if not a: raise HTTPException(409,"Runtime agent is offline")
    await a.send_json({"type":"files_list","path":path})
    return {"queued":True,"path":path}

@app.get("/api/catalog/runtimes")
async def runtimes():
    return {"runtimes":RUNTIMES}

@app.get("/api/catalog/versions")
async def versions():
    try:
        return {"versions":await runtime_catalog()}
    except Exception as e:
        raise HTTPException(502,f"Version catalog unavailable: {e}")

@app.get("/api/catalog/search")
async def catalog(q:str=Query(""),provider:str="modrinth",mc:str="1.21.10",loader:str="fabric",type:str="mod",u=Depends(user)):
    if provider=="modrinth": return {"items":await modrinth_search(q,mc,loader,type)}
    if provider=="curseforge": return {"items":await curseforge_search(q,mc,loader,type)}
    raise HTTPException(400,"Invalid provider")

@app.post("/api/servers/{sid}/install")
async def install(sid,body:InstallRequest,u=Depends(user)):
    s=store.get_server(sid);owns(s,u)
    if body.provider=="modrinth":
        v=await modrinth_version(body.project_id,s["mc_version"],body.loader)
        f=next((x for x in v.get("files",[]) if x.get("primary")),v.get("files",[None])[0])
        if not f: raise HTTPException(404,"No compatible download")
        if body.type=="modpack":
            p={"url":f["url"],"name":v["name"],"target":"modpack","sha1":f.get("hashes",{}).get("sha1")}
        else:
            p={"url":f["url"],"name":v["name"],"target":"plugins" if body.type=="plugin" else "mods"}
    elif body.provider=="curseforge":
        f=await curseforge_file(int(body.project_id),s["mc_version"],body.loader)
        p={"url":f["downloadUrl"],"name":f["displayName"],"target":"mods"}
    else: raise HTTPException(400,"Invalid provider")
    a=AGENTS.get(sid)
    if not a: raise HTTPException(409,"Runtime agent is offline")
    await a.send_json({"type":"install",**p})
    return {"ok":True,"queued":p["name"]}

@app.websocket("/agent/ws")
async def agent(ws:WebSocket,server_id:str,token:str):
    s=store.get_server(server_id)
    if not s or not hmac.compare_digest(str(s.get("agent_token","")),token):
        await ws.close(code=4401);return
    await ws.accept();AGENTS[server_id]=ws
    try:
        async for raw in ws.iter_text():
            m=json.loads(raw);t=m.get("type")
            if t=="hello":
                store.update_server(server_id,metrics=m.get("data",{}),status="online")
            elif t=="metrics":
                data=m.get("data",{})
                store.update_server(server_id,metrics=data,status="online" if data.get("minecraft_running") else "offline",players_online=data.get("players_online",0),players=data.get("players",[]),max_players=data.get("max_players",20))
                await broadcast(server_id,m)
            elif t=="players":
                store.update_server(server_id,players_online=m.get("count",0),players=m.get("players",[]),max_players=m.get("max_players",20))
                await broadcast(server_id,m)
            elif t in {"log","install","files"}: await broadcast(server_id,m)
    except WebSocketDisconnect: pass
    finally:
        if AGENTS.get(server_id) is ws: AGENTS.pop(server_id,None)
        try: store.update_server(server_id,status="offline")
        except Exception: pass

@app.websocket("/api/servers/{sid}/console")
async def console(ws:WebSocket,sid:str,token:str):
    s=store.get_server(sid)
    try: u=google_user("Bearer "+token)
    except HTTPException:
        await ws.close(code=4401);return
    if not s or s.get("owner_id")!=u["id"]:
        await ws.close(code=4404);return
    await ws.accept();BROWSERS.setdefault(sid,set()).add(ws)
    try:
        while True:
            m=await ws.receive_json();a=AGENTS.get(sid)
            if not a: await ws.send_json({"type":"error","message":"Minecraft runtime agent is offline"});continue
            await a.send_json(m)
    except WebSocketDisconnect: pass
    finally: BROWSERS.get(sid,set()).discard(ws)

async def broadcast(sid,payload):
    dead=[]
    for ws in BROWSERS.get(sid,set()):
        try: await ws.send_json(payload)
        except Exception: dead.append(ws)
    for ws in dead: BROWSERS.get(sid,set()).discard(ws)

# Serve the same production UI from Cloud Run. API and frontend therefore share one origin.
app.mount("/", StaticFiles(directory="/app/web", html=True), name="web")
