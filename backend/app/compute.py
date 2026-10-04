from __future__ import annotations
import base64,json,time
from pathlib import Path
from typing import Any
import httpx
from google.cloud import compute_v1
from .config import settings
from .runtime import resolve_runtime,java_major_for_minecraft

UA="Mineserver/3.0 (https://github.com/akatsukixpain12-stack/mineserver)"

async def resolve_jar_url(software,mc):
    return await resolve_runtime(software,mc)

def agent_source():
    return (Path(__file__).resolve().parents[1]/"agent"/"agent.py").read_text()

def startup_script(server:dict[str,Any],binary_or_jar_url):
    agent_b64=base64.b64encode(agent_source().encode()).decode()
    meta=base64.b64encode(json.dumps({
        "server_id":server["id"],
        "agent_token":server["agent_token"],
        "control_url":settings.control_url,
        "backup_bucket":settings.backup_bucket,
        "jar_url":binary_or_jar_url,
        "memory_mb":server.get("memory_mb",2048),
        "runtime":server.get("software","vanilla"),
        "java_major":java_major_for_minecraft(server.get("mc_version","1.21.10")),
    }).encode()).decode()
    runtime=server.get("software","vanilla")
    java_major=java_major_for_minecraft(server.get("mc_version","1.21.10"))
    if runtime=="mineserver":
        installer=f'''\
if [ ! -f /opt/mineserver/server/mineserver ]; then
  curl -fL --retry 5 -A '{UA}' -o /opt/mineserver/server/mineserver '{binary_or_jar_url}'
  chmod +x /opt/mineserver/server/mineserver
fi
'''
    else:
        installer=f'''\
if [ ! -f /opt/mineserver/server/server.jar ] && [ ! -f /opt/mineserver/server/installer.jar ] && [ ! -f /opt/mineserver/server/run.sh ]; then
  curl -fL --retry 5 -A '{UA}' -o /opt/mineserver/server/server.jar '{binary_or_jar_url}'
fi
if [ "{runtime}" = "forge" ] || [ "{runtime}" = "neoforge" ]; then
  if [ ! -f /opt/mineserver/server/run.sh ] && [ -f /opt/mineserver/server/server.jar ]; then
    mv /opt/mineserver/server/server.jar /opt/mineserver/server/installer.jar
    cd /opt/mineserver/server
    java -jar installer.jar --installServer
    rm -f installer.jar
  fi
fi
'''
    return f'''\
#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y openjdk-8-jre-headless openjdk-17-jre-headless openjdk-21-jre-headless openjdk-25-jre-headless python3 python3-pip curl ca-certificates
python3 -m pip install --break-system-packages --no-cache-dir psutil==7.0.0 websockets==15.0.1 google-cloud-storage==2.19.0
mkdir -p /opt/mineserver/server
printf '%s' '{agent_b64}' | base64 -d > /opt/mineserver/agent.py
printf '%s' '{meta}' | base64 -d > /opt/mineserver/config.json
JAVA_MAJOR=$(python3 -c 'import json; print(json.load(open("/opt/mineserver/config.json"))["java_major"])')
export JAVA_HOME="/usr/lib/jvm/java-$JAVA_MAJOR-openjdk-amd64"
export PATH="$JAVA_HOME/bin:$PATH"
cd /opt/mineserver/server
{installer}
if [ "{runtime}" != "mineserver" ]; then
  printf 'eula=true\\nserver-port=25565\\nserver-ip=\\nmax-players=20\\nmotd=Mineserver Server\\n' > server.properties
fi
cat >/etc/systemd/system/mineserver-agent.service <<'UNIT'
[Unit]
After=network-online.target
Wants=network-online.target
[Service]
WorkingDirectory=/opt/mineserver
ExecStart=/usr/bin/python3 /opt/mineserver/agent.py
Restart=always
RestartSec=4
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now mineserver-agent
'''

def wait(op):
    op.result(timeout=900)

def ensure_firewall():
    fw=compute_v1.FirewallsClient()
    name="mineserver-minecraft-25565"
    try:
        fw.get(project=settings.project_id,firewall=name)
        return
    except Exception:
        pass
    rule=compute_v1.Firewall(
        name=name,
        network=f"projects/{settings.project_id}/global/networks/{settings.network}",
        direction="INGRESS",
        source_ranges=["0.0.0.0/0"],
        target_tags=["mineserver-minecraft"],
        allowed=[compute_v1.Allowed(protocol="tcp",ports=["25565"])],
    )
    wait(fw.insert(project=settings.project_id,firewall_resource=rule))

def create_vm(server,jar_url):
    zone=server.get("zone") or settings.compute_zone
    if not settings.project_id:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT is required")
    if not server.get("vm_name"):
        raise RuntimeError("Server VM name is missing")
    ensure_firewall()
    client=compute_v1.InstancesClient()
    disk=compute_v1.AttachedDisk(
        boot=True,
        auto_delete=True,
        initialize_params=compute_v1.AttachedDiskInitializeParams(
            source_image="projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-amd64",
            disk_size_gb=int(server.get("disk_gb") or settings.disk_gb),
            disk_type=f"projects/{settings.project_id}/zones/{zone}/diskTypes/pd-balanced",
        ),
    )
    nic=compute_v1.NetworkInterface(
        network=f"projects/{settings.project_id}/global/networks/{settings.network}",
        access_configs=[compute_v1.AccessConfig(name="External NAT",type_="ONE_TO_ONE_NAT")],
    )
    metadata=compute_v1.Metadata(
        items=[compute_v1.Items(key="startup-script",value=startup_script(server,jar_url))]
    )
    instance=compute_v1.Instance(
        name=server["vm_name"],
        machine_type=f"zones/{zone}/machineTypes/{settings.machine_type}",
        disks=[disk],
        network_interfaces=[nic],
        metadata=metadata,
        tags=compute_v1.Tags(items=["mineserver-minecraft"]),
        labels={"mineserver":"true","mineserver-server":server["id"][:63]},
    )
    wait(client.insert(project=settings.project_id,zone=zone,instance_resource=instance))
    for _ in range(120):
        cur=client.get(project=settings.project_id,zone=zone,instance=server["vm_name"])
        if cur.network_interfaces and cur.network_interfaces[0].access_configs:
            ip=cur.network_interfaces[0].access_configs[0].nat_i_p
            if ip:
                return {
                    "public_ip":ip,
                    "game_address":f"{ip}:25565",
                    "vm_id":cur.id or "",
                }
        time.sleep(2)
    return {"public_ip":None,"game_address":None,"vm_id":""}

def vm_action(vm,action,zone=None):
    if not vm:
        raise RuntimeError("VM is not provisioned")
    zone=zone or settings.compute_zone
    client=compute_v1.InstancesClient()
    method={"start":client.start,"stop":client.stop,"reset":client.reset}.get(action)
    if method is None:
        raise ValueError("Invalid VM action")
    wait(method(project=settings.project_id,zone=zone,instance=vm))

def delete_vm(vm,zone=None):
    if not vm:
        return
    zone=zone or settings.compute_zone
    try:
        wait(compute_v1.InstancesClient().delete(project=settings.project_id,zone=zone,instance=vm))
    except Exception as exc:
        if "not found" not in str(exc).lower():
            raise