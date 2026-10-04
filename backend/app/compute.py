from __future__ import annotations
import base64,json,time
from pathlib import Path
from typing import Any
import httpx
from google.cloud import compute_v1
from .config import settings
UA="MineHub/1.0 (https://github.com/akatsukixpain12-stack/mineserver)"
async def resolve_jar_url(software,mc):
    if software=="paper":
        async with httpx.AsyncClient(timeout=30) as c:r=await c.get(f"https://fill.papermc.io/v3/projects/paper/versions/{mc}/builds",headers={"User-Agent":UA});r.raise_for_status()
        a=[x for x in r.json() if x.get("channel")=="STABLE"]
        if not a:raise ValueError(f"Paper has no stable build for {mc}")
        return a[0]["downloads"]["server:default"]["url"]
    if software=="fabric":
        async with httpx.AsyncClient(timeout=30) as c:
            loader=(await c.get(f"https://meta.fabricmc.net/v2/versions/loader/{mc}")).json()[0]["version"]
            installer=(await c.get("https://meta.fabricmc.net/v2/versions/installer")).json()[0]["version"]
        return f"https://meta.fabricmc.net/v2/versions/loader/{mc}/{loader}/{installer}/server/jar"
    if software=="vanilla":
        async with httpx.AsyncClient(timeout=30) as c:
            m=(await c.get("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")).json()
            hit=next((x for x in m["versions"] if x["id"]==mc),None)
            v=(await c.get(hit["url"])).json() if hit else None
        if not v:raise ValueError(f"Minecraft {mc} not found")
        return v["downloads"]["server"]["url"]
    raise ValueError("Supported runtime: Paper, Fabric, Vanilla")
def agent_source():return (Path(__file__).resolve().parents[1]/"agent"/"agent.py").read_text()
def startup_script(server:dict[str,Any],jar_url):
    a=base64.b64encode(agent_source().encode()).decode()
    meta=base64.b64encode(json.dumps({"server_id":server["id"],"agent_token":server["agent_token"],"control_url":settings.control_url,"jar_url":jar_url,"memory_mb":server.get("memory_mb",2048)}).encode()).decode()
    return f"""#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y openjdk-21-jre-headless python3 python3-pip curl ca-certificates
mkdir -p /opt/minehub/server /opt/minehub
printf '%s' '{a}' | base64 -d > /opt/minehub/agent.py
printf '%s' '{meta}' | base64 -d > /opt/minehub/config.json
cd /opt/minehub/server
if [ ! -f server.jar ]; then curl -fL --retry 5 -A '{UA}' -o server.jar '{jar_url}'; fi
printf 'eula=true\\nserver-port=25565\\nserver-ip=\\nmax-players=20\\nmotd=MineHub Server\\n' > server.properties
cat >/etc/systemd/system/minehub-agent.service <<'UNIT'
[Unit]
After=network-online.target
Wants=network-online.target
[Service]
WorkingDirectory=/opt/minehub
ExecStart=/usr/bin/python3 /opt/minehub/agent.py
Restart=always
RestartSec=4
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now minehub-agent
"""
def wait(op):op.result(timeout=600)
def ensure_firewall():
    fw=compute_v1.FirewallsClient();name="minehub-minecraft-25565"
    try:fw.get(project=settings.project_id,firewall=name);return
    except Exception:pass
    rule=compute_v1.Firewall(name=name,network=f"projects/{settings.project_id}/global/networks/{settings.network}",direction="INGRESS",source_ranges=["0.0.0.0/0"],target_tags=["minehub-minecraft"],allowed=[compute_v1.Allowed(protocol="tcp",ports=["25565"])])
    wait(fw.insert(project=settings.project_id,firewall_resource=rule))
def create_vm(server,jar_url):
    if not settings.project_id:raise RuntimeError("GOOGLE_CLOUD_PROJECT is required")
    ensure_firewall();c=compute_v1.InstancesClient()
    disk=compute_v1.AttachedDisk(boot=True,auto_delete=True,initialize_params=compute_v1.AttachedDiskInitializeParams(source_image="projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-amd64",disk_size_gb=settings.disk_gb,disk_type=f"projects/{settings.project_id}/zones/{settings.compute_zone}/diskTypes/pd-balanced"))
    nic=compute_v1.NetworkInterface(network=f"projects/{settings.project_id}/global/networks/{settings.network}",access_configs=[compute_v1.AccessConfig(name="External NAT",type_="ONE_TO_ONE_NAT")])
    md=compute_v1.Metadata(items=[compute_v1.Items(key="startup-script",value=startup_script(server,jar_url))])
    ins=compute_v1.Instance(name=server["vm_name"],machine_type=f"zones/{settings.compute_zone}/machineTypes/{settings.machine_type}",disks=[disk],network_interfaces=[nic],metadata=md,tags=compute_v1.Tags(items=["minehub-minecraft"]),labels={"minehub":"true","minehub-server":server["id"][:63]})
    wait(c.insert(project=settings.project_id,zone=settings.compute_zone,instance_resource=ins))
    for _ in range(90):
        cur=c.get(project=settings.project_id,zone=settings.compute_zone,instance=server["vm_name"])
        if cur.network_interfaces and cur.network_interfaces[0].access_configs:
            ip=cur.network_interfaces[0].access_configs[0].nat_i_p
            if ip:return {"public_ip":ip,"game_address":f"{ip}:25565"}
        time.sleep(2)
    return {"public_ip":None,"game_address":None}
def vm_action(vm,action):
    c=compute_v1.InstancesClient();op={"start":c.start,"stop":c.stop,"reset":c.reset}[action](project=settings.project_id,zone=settings.compute_zone,instance=vm);wait(op)
def delete_vm(vm):
    try:wait(compute_v1.InstancesClient().delete(project=settings.project_id,zone=settings.compute_zone,instance=vm))
    except Exception as e:
        if "not found" not in str(e).lower():raise
