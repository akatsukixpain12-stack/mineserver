from __future__ import annotations
import re
import xml.etree.ElementTree as ET
import httpx
from fastapi import HTTPException

UA="MineHub/2.0"

RUNTIMES=[
 {"id":"vanilla","name":"Vanilla","kind":"server","family":"official","loaders":[],"description":"Official Mojang Java server"},
 {"id":"paper","name":"Paper","kind":"server","family":"paper","loaders":[],"description":"High-performance Bukkit-compatible server"},
 {"id":"folia","name":"Folia","kind":"server","family":"paper","loaders":[],"description":"Regionized Paper fork for high concurrency"},
 {"id":"purpur","name":"Purpur","kind":"server","family":"paper","loaders":[],"description":"Highly configurable Paper fork"},
 {"id":"fabric","name":"Fabric","kind":"server","family":"modded","loaders":["fabric"],"description":"Lightweight modding platform"},
 {"id":"quilt","name":"Quilt","kind":"server","family":"modded","loaders":["quilt"],"description":"Modern Fabric-compatible mod loader"},
 {"id":"forge","name":"Forge","kind":"server","family":"modded","loaders":["forge"],"description":"Classic Minecraft mod loader"},
 {"id":"neoforge","name":"NeoForge","kind":"server","family":"modded","loaders":["neoforge"],"description":"Modern Forge-family mod loader"},
 ]

async def get_json(client,url,params=None):
    r=await client.get(url,params=params,headers={"User-Agent":UA})
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
    try:
        data=await get_json(client,"https://meta.quiltmc.org/v3/versions/game")
        return [{"id":x["version"],"type":"release" if x.get("stable") else "other"} for x in data]
    except Exception:
        return []

async def maven_versions(client,base):
    r=await client.get(base,headers={"User-Agent":UA})
    r.raise_for_status()
    root=ET.fromstring(r.text)
    return [{"id":x.text,"type":"release"} for x in root.findall(".//version") if x.text]

async def catalog():
    async with httpx.AsyncClient(timeout=25) as c:
        results={}
        results["vanilla"]=await vanilla_versions(c)
        for p in ("paper","folia","purpur"):
            try: results[p]=await paper_versions(c,p)
            except Exception: results[p]=[]
        results["fabric"]=await fabric_versions(c)
        results["quilt"]=await quilt_versions(c)
        try: results["forge"]=await maven_versions(c,"https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml")
        except Exception: results["forge"]=[]
        try: results["neoforge"]=await maven_versions(c,"https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml")
        except Exception: results["neoforge"]=[]
        results["sponge"]=[]
        return results

async def resolve_runtime(runtime,mc):
    runtime=runtime.lower()
    async with httpx.AsyncClient(timeout=35) as c:
        if runtime=="vanilla":
            data=await get_json(c,"https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")
            hit=next((x for x in data["versions"] if x["id"]==mc),None)
            if not hit: raise ValueError(f"Unknown Minecraft version: {mc}")
            meta=await get_json(c,hit["url"])
            return meta["downloads"]["server"]["url"]

        if runtime in {"paper","folia","purpur"}:
            data=await get_json(c,f"https://api.papermc.io/v2/projects/{runtime}")
            if mc not in data.get("versions",[]): raise ValueError(f"{runtime} does not publish Minecraft {mc}")
            builds=await get_json(c,f"https://api.papermc.io/v2/projects/{runtime}/versions/{mc}/builds")
            stable=[x for x in builds.get("builds",[]) if x.get("channel","default") in {"default","STABLE","stable"}]
            build=(stable or builds.get("builds",[]))[-1]
            b=build["build"]
            downloads=build.get("downloads",{})
            if "server:default" in downloads:
                return downloads["server:default"]["url"]
            return f"https://api.papermc.io/v2/projects/{runtime}/versions/{mc}/builds/{b}/downloads/{runtime}-{mc}-{b}.jar"

        if runtime=="fabric":
            loaders=await get_json(c,f"https://meta.fabricmc.net/v2/versions/loader/{mc}")
            if not loaders: raise ValueError(f"Fabric does not publish Minecraft {mc}")
            loader=loaders[0]["version"]
            installers=await get_json(c,"https://meta.fabricmc.net/v2/versions/installer")
            installer=installers[0]["version"]
            return f"https://meta.fabricmc.net/v2/versions/loader/{mc}/{loader}/{installer}/server/jar"

        if runtime=="quilt":
            loaders=await get_json(c,f"https://meta.quiltmc.org/v3/versions/loader/{mc}")
            if not loaders: raise ValueError(f"Quilt does not publish Minecraft {mc}")
            loader=loaders[0]["version"]
            installers=await get_json(c,"https://meta.quiltmc.org/v3/versions/installer")
            installer=installers[0]["version"]
            return f"https://meta.quiltmc.org/v3/versions/loader/{mc}/{loader}/{installer}/server/jar"

        if runtime=="forge":
            data=await maven_versions(c,"https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml")
            candidates=[x["id"] for x in data if x["id"].startswith(mc+"-")]
            if not candidates: raise ValueError(f"Forge does not publish {mc}")
            ver=candidates[-1]
            return f"https://maven.minecraftforge.net/net/minecraftforge/forge/{ver}/forge-{ver}-installer.jar"

        if runtime=="neoforge":
            data=await maven_versions(c,"https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml")
            candidates=[x["id"] for x in data if mc.replace(".","") in x["id"] or x["id"].startswith(mc+"-")]
            if not candidates: raise ValueError(f"NeoForge does not publish {mc}")
            ver=candidates[-1]
            return f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{ver}/neoforge-{ver}-installer.jar"

        raise ValueError(f"Unsupported runtime: {runtime}")
