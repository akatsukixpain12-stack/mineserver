from __future__ import annotations
import json,httpx
from fastapi import HTTPException
from .config import settings
MODRINTH="https://api.modrinth.com/v2";CURSEFORGE="https://api.curseforge.com/v1"
def mh():return {"User-Agent":settings.modrinth_user_agent}
async def modrinth_search(query,mc,loader,project_type):
    facets=[[f"versions:{mc}"]]
    if loader:facets.append([f"categories:{loader}"])
    if project_type:facets.append([f"project_type:{project_type}"])
    async with httpx.AsyncClient(timeout=20) as c:r=await c.get(f"{MODRINTH}/search",params={"query":query,"facets":json.dumps(facets),"limit":30},headers=mh())
    if r.status_code>=400:raise HTTPException(502,"Modrinth search failed")
    return [{"provider":"modrinth","id":x["project_id"],"name":x["title"],"description":x.get("description",""),"icon":x.get("icon_url"),"downloads":x.get("downloads",0),"type":x.get("project_type",project_type),"slug":x.get("slug")} for x in r.json().get("hits",[])]
async def modrinth_version(pid,mc,loader):
    async with httpx.AsyncClient(timeout=20) as c:r=await c.get(f"{MODRINTH}/project/{pid}/version",params={"game_versions":json.dumps([mc]),"loaders":json.dumps([loader])},headers=mh())
    data=r.json() if r.content else []
    if r.status_code>=400 or not data:raise HTTPException(404,"No compatible Modrinth version")
    return next((x for x in data if x.get("files")),data[0])
async def curseforge_search(query,mc,loader,project_type):
    if not settings.curseforge_api_key:raise HTTPException(503,"CURSEFORGE_API_KEY is not configured")
    lm={"forge":1,"fabric":4,"quilt":5,"neoforge":6};p={"gameId":432,"classId":4471 if project_type=="modpack" else (5 if project_type=="plugin" else 6),"searchFilter":query,"gameVersion":mc,"pageSize":30}
    if loader in lm:p["modLoaderType"]=lm[loader]
    h={"Accept":"application/json","x-api-key":settings.curseforge_api_key}
    async with httpx.AsyncClient(timeout=20) as c:r=await c.get(f"{CURSEFORGE}/mods/search",params=p,headers=h)
    if r.status_code>=400:raise HTTPException(502,"CurseForge search failed")
    return [{"provider":"curseforge","id":x["id"],"name":x["name"],"description":x.get("summary",""),"icon":(x.get("logo") or {}).get("url"),"downloads":x.get("downloadCount",0),"type":project_type,"slug":x.get("slug")} for x in r.json().get("data",[])]
async def curseforge_file(mid,mc,loader):
    if not settings.curseforge_api_key:raise HTTPException(503,"CURSEFORGE_API_KEY is not configured")
    lm={"forge":1,"fabric":4,"quilt":5,"neoforge":6};p={"gameVersion":mc,"pageSize":50}
    if loader in lm:p["modLoaderType"]=lm[loader]
    h={"Accept":"application/json","x-api-key":settings.curseforge_api_key}
    async with httpx.AsyncClient(timeout=20) as c:r=await c.get(f"{CURSEFORGE}/mods/{mid}/files",params=p,headers=h)
    data=r.json().get("data",[]) if r.content else []
    if r.status_code>=400 or not data:raise HTTPException(404,"No compatible CurseForge file")
    return next((x for x in data if x.get("downloadUrl") and x.get("isAvailable",True)),data[0])
