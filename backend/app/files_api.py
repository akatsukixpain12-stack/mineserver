from __future__ import annotations
import asyncio,base64,os,shlex
from pathlib import Path
from fastapi import HTTPException
ROOT=Path("/opt/mineserver/server")
ALLOWED={"server.properties","eula.txt","whitelist.json","ops.json","banned-players.json","banned-ips.json"}
def safe(rel:str)->Path:
    rel=rel.strip().replace("\\","/")
    p=(ROOT/rel).resolve()
    if p!=ROOT and ROOT not in p.parents:raise HTTPException(400,"Invalid path")
    return p
def list_dir(rel=""):
    p=safe(rel)
    if not p.exists():raise HTTPException(404,"Path not found")
    if not p.is_dir():raise HTTPException(400,"Not a directory")
    return [{"name":x.name,"path":str(x.relative_to(ROOT)),"directory":x.is_dir(),"size":x.stat().st_size if x.is_file() else None} for x in sorted(p.iterdir(),key=lambda x:(not x.is_dir(),x.name.lower()))]
def read_file(rel):
    p=safe(rel)
    if not p.is_file():raise HTTPException(404,"File not found")
    if p.stat().st_size>2_000_000:raise HTTPException(413,"File too large")
    try:return p.read_text()
    except UnicodeDecodeError:raise HTTPException(415,"Binary files cannot be edited here")
def write_file(rel,content):
    p=safe(rel)
    if p.name not in ALLOWED and not any(str(p).startswith(str(ROOT/x)) for x in [Path("config"),Path("plugins"),Path("mods")]):raise HTTPException(403,"File is not editable")
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content);return {"path":str(p.relative_to(ROOT)),"bytes":len(content.encode())}
def delete_file(rel):
    p=safe(rel)
    if p.is_dir():raise HTTPException(400,"Directory deletion disabled by API")
    if p.name=="server.jar":raise HTTPException(403,"Server binary cannot be deleted")
    p.unlink(missing_ok=True);return {"ok":True}
