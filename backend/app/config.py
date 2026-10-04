from __future__ import annotations
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    app_name:str=os.getenv("APP_NAME","Mineserver")
    project_id:str=os.getenv("GOOGLE_CLOUD_PROJECT",os.getenv("GCP_PROJECT",""))
    compute_zone:str=os.getenv("COMPUTE_ZONE","asia-south1-a")
    network:str=os.getenv("COMPUTE_NETWORK","default")
    machine_type:str=os.getenv("MINECRAFT_MACHINE_TYPE","e2-small")
    disk_gb:int=int(os.getenv("MINECRAFT_DISK_GB","20"))
    control_url:str=os.getenv("CONTROL_URL","http://localhost:8080").rstrip("/")
    admin_token:str=os.getenv("ADMIN_TOKEN","")
    google_client_id:str=os.getenv("GOOGLE_CLIENT_ID","").strip()
    cors_origins:str=os.getenv("CORS_ORIGINS","http://localhost:8080").strip()
    curseforge_api_key:str=os.getenv("CURSEFORGE_API_KEY","")
    mineserver_binary_url:str=os.getenv(
        "MINESERVER_BINARY_URL",
        "https://github.com/akatsukixpain12-stack/mineserver/releases/download/mineserver-nightly/mineserver-linux-x64",
    )
    modrinth_user_agent:str=os.getenv("MODRINTH_USER_AGENT","akatsukixpain12-stack/mineserver/3.0")
    firestore_collection:str=os.getenv("FIRESTORE_COLLECTION","mineserver_servers")
    backup_bucket:str=os.getenv("BACKUP_BUCKET","")
    local_db:str=os.getenv("LOCAL_DB","./mineserver.db")

    @property
    def cors_list(self):
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

settings=Settings()
