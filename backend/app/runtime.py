from __future__ import annotations
import asyncio,re,time
import xml.etree.ElementTree as ET
import httpx
from .config import settings

UA="Mineserver/3.0"
_VERSION_CACHE={}
_VERSION_CACHE_TTL=300
PAPER_PROJECTS={"paper","folia","purpur"}

RUNTIMES=[
 {"id":"vanilla","name":"Vanilla","kind":"server","family":"official","loaders":[],"description":"Official Mojang Java server"},
 {"id":"paper","name":"Paper","kind":"server","family":"paper","loaders":[],"description":"High-performance Bukkit-compatible server"},
 {"id":"folia","name":"Folia","kind":"server","family":"paper","loaders":[],"description":"Regionized Paper fork for high concurrency"},
 {"id":"purpur","name":"Purpur","kind":"server","family":"paper","loaders":[],"description":"Highly configurable Paper fork"},
 {"id":"fabric","name":"Fabric","kind":"server","family":"modded","loaders":["fabric"],"description":"Lightweight modding platform"},
 {"id":"quilt","name":"Quilt","kind":"server","family":"modded","loaders":["quilt"],"description":"Modern Fabric-compatible mod loader"},
 {"id":"forge","name":"Forge","kind":"server","family":"modded","loaders":["forge"],"description":"Classic Minecraft mod loader"},
 {"id":"neoforge","name":"NeoForge","kind":"server","family":"modded","loaders":["neoforge"],"description":"Modern Forge-family mod loader"},
 {"id":"mineserver","name":"Mineserver Native","kind":"server","family":"native","loaders":[],"description":"Headless Rust Minecraft server core built by Mineserver"},
]

async def get_json(client,url,params=None):
    r=await client.get(url,params=params,headers={"User-Agent":UA,"Accept":"application/json"})
    r.raise_for_status()
    return r.json()

async def vanilla_versions(client):
    data=await get_json(client,"https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")
    return [{"id":x["id"],"type":x.get("type","release"),"release_time":x.get("releaseTime")} for x in data.get("versions",[])]

async def paper_versions(client,project):
    data=await get_json(client,f"https://api.papermc.io/v2/projects/{project}")
    return [{"id":x,"type":"release"} for x in data.get("versions",[])]

async def fabric_versions(client):
    data=await get_json(client,"https://meta.fabricmc.net/v2/versions/game")
    return [{"id":x["version"],"type":"release" if x.get("stable") else "other"} for x in data]

async def quilt_versions(client):
    data=await get_json(client,"https://meta.quiltmc.org/v3/versions/game")
    return [{"id":x["version"],"type":"release" if x.get("stable") else "other"} for x in data]

async def maven_versions(client,base):
    r=await client.get(base,headers={"User-Agent":UA})
    r.raise_for_status()
    root=ET.fromstring(r.text)
    return [{"id":x.text,"type":"release"} for x in root.findall(".//version") if x.text]

async def mineserver_versions(client):
    r=await client.get(
        "https://api.github.com/repos/akatsukixpain12-stack/mineserver/releases",
        params={"per_page":20},
        headers={"User-Agent":UA,"Accept":"application/vnd.github+json"},
    )
    r.raise_for_status()
    out=[]
    for release in r.json():
        assets=release.get("assets",[])
        binary=next((a for a in assets if a.get("name")=="mineserver-linux-x64"),None)
        if not binary:
            continue
        out.append({
            "id":release.get("tag_name") or release.get("name"),
            "type":"native",
            "published_at":release.get("published_at"),
            "asset_url":binary.get("browser_download_url"),
            "minecraft":"bundled",
        })
    if not out:
        fallback=settings.mineserver_binary_url
        if fallback:
            out=[{"id":"mineserver-nightly","type":"native","published_at":None,"asset_url":fallback,"minecraft":"bundled"}]
    return out

async def safe_call(fn):
    try:
        return await fn()
    except Exception:
        return []

def cache_set(key,data):
    _VERSION_CACHE[key]=(time.monotonic()+_VERSION_CACHE_TTL,data)
    return data

async def catalog():
    async with httpx.AsyncClient(timeout=15) as c:
        keys=["vanilla","paper","folia","purpur","fabric","quilt","forge","neoforge","mineserver"]
        funcs={
            "vanilla":safe_call(lambda:vanilla_versions(c)),
            "paper":safe_call(lambda:paper_versions(c,"paper")),
            "folia":safe_call(lambda:paper_versions(c,"folia")),
            "purpur":safe_call(lambda:paper_versions(c,"purpur")),
            "fabric":safe_call(lambda:fabric_versions(c)),
            "quilt":safe_call(lambda:quilt_versions(c)),
            "forge":safe_call(lambda:maven_versions(c,"https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml")),
            "neoforge":safe_call(lambda:maven_versions(c,"https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml")),
            "mineserver":safe_call(lambda:mineserver_versions(c)),
        }
        values=await asyncio.gather(*(funcs[k] for k in keys))
        return {k:cache_set(k,v) for k,v in zip(keys,values)}

async def versions_for(runtime:str):
    runtime=runtime.lower()
    cached=_VERSION_CACHE.get(runtime)
    if cached and cached[0]>time.monotonic():
        return {runtime:cached[1]}
    async with httpx.AsyncClient(timeout=15) as c:
        if runtime=="vanilla": data=await vanilla_versions(c)
        elif runtime in PAPER_PROJECTS: data=await paper_versions(c,runtime)
        elif runtime=="fabric": data=await fabric_versions(c)
        elif runtime=="quilt": data=await quilt_versions(c)
        elif runtime=="forge": data=await maven_versions(c,"https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml")
        elif runtime=="neoforge": data=await maven_versions(c,"https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml")
        elif runtime=="mineserver": data=await mineserver_versions(c)
        else: raise ValueError(f"Unknown runtime: {runtime}")
    return {runtime:cache_set(runtime,data)}

def _forge_version(candidates,mc):
    exact=[x["id"] for x in candidates if x["id"].startswith(mc+"-")]
    return exact[-1] if exact else None

def _neoforge_version(candidates,mc):
    flat=mc.replace(".","")
    exact=[x["id"] for x in candidates if x["id"].startswith(mc+"-") or flat in x["id"]]
    return exact[-1] if exact else None

async def resolve_runtime(runtime,mc):
    runtime=runtime.lower()
    async with httpx.AsyncClient(timeout=45) as c:
        if runtime=="vanilla":
            data=await get_json(c,"https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")
            hit=next((x for x in data["versions"] if x["id"]==mc),None)
            if not hit: raise ValueError(f"Unknown Minecraft version: {mc}")
            meta=await get_json(c,hit["url"])
            return meta["downloads"]["server"]["url"]

        if runtime in PAPER_PROJECTS:
            data=await get_json(c,f"https://api.papermc.io/v2/projects/{runtime}")
            if mc not in data.get("versions",[]):
                raise ValueError(f"{runtime} does not publish Minecraft {mc}")
            builds=await get_json(c,f"https://api.papermc.io/v2/projects/{runtime}/versions/{mc}/builds")
            rows=builds.get("builds",[])
            if not rows: raise ValueError(f"{runtime} has no builds for {mc}")
            stable=[x for x in rows if x.get("channel","default").lower() in {"default","stable"}]
            build=(stable or rows)[-1]
            downloads=build.get("downloads",{})
            if "server:default" in downloads:
                return downloads["server:default"]["url"]
            number=build["build"]
            return f"https://api.papermc.io/v2/projects/{runtime}/versions/{mc}/builds/{number}/downloads/{runtime}-{mc}-{number}.jar"

        if runtime=="fabric":
            loaders=await get_json(c,f"https://meta.fabricmc.net/v2/versions/loader/{mc}")
            if not loaders: raise ValueError(f"Fabric does not publish Minecraft {mc}")
            installer_rows=await get_json(c,"https://meta.fabricmc.net/v2/versions/installer")
            if not installer_rows: raise ValueError("Fabric installer metadata unavailable")
            return f"https://meta.fabricmc.net/v2/versions/loader/{mc}/{loaders[0]['version']}/{installer_rows[0]['version']}/server/jar"

        if runtime=="quilt":
            loaders=await get_json(c,f"https://meta.quiltmc.org/v3/versions/loader/{mc}")
            if not loaders: raise ValueError(f"Quilt does not publish Minecraft {mc}")
            installer_rows=await get_json(c,"https://meta.quiltmc.org/v3/versions/installer")
            if not installer_rows: raise ValueError("Quilt installer metadata unavailable")
            return f"https://meta.quiltmc.org/v3/versions/loader/{mc}/{loaders[0]['version']}/{installer_rows[0]['version']}/server/jar"

        if runtime=="forge":
            rows=await maven_versions(c,"https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml")
            version=_forge_version(rows,mc)
            if not version: raise ValueError(f"Forge does not publish {mc}")
            return f"https://maven.minecraftforge.net/net/minecraftforge/forge/{version}/forge-{version}-installer.jar"

        if runtime=="neoforge":
            rows=await maven_versions(c,"https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml")
            version=_neoforge_version(rows,mc)
            if not version: raise ValueError(f"NeoForge does not publish {mc}")
            return f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{version}/neoforge-{version}-installer.jar"

        if runtime=="mineserver":
            rows=await mineserver_versions(c)
            hit=next((x for x in rows if x["id"]==mc),None) or (rows[0] if rows else None)
            if not hit: raise ValueError("No Mineserver native build is published")
            return hit["asset_url"]

        raise ValueError(f"Unsupported runtime: {runtime}")

def java_major_for_minecraft(mc:str)->int:
    s=mc.lower()
    if s.startswith(("26.","27.","28.")):
        return 25
    m=re.match(r"1\.(\d+)(?:\.(\d+))?",s)
    if not m:
        return 25
    n=int(m.group(1))
    patch=int(m.group(2) or 0)
    if n>20 or (n==20 and patch>=5):
        return 21
    if n>=18:
        return 17
    return 8
