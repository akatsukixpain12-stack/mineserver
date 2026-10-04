from __future__ import annotations
import shutil,time
from pathlib import Path
ROOT=Path("/opt/minehub/server");BACK=Path("/opt/minehub/backups")
def make_backup(include_world=True):
    BACK.mkdir(parents=True,exist_ok=True);stamp=time.strftime("%Y%m%d-%H%M%S");name=f"backup-{stamp}";archive=shutil.make_archive(str(BACK/name),"zip",root_dir=ROOT,base_dir="." if include_world else "server.properties");return {"name":Path(archive).name,"path":archive,"bytes":Path(archive).stat().st_size}
def list_backups():
    BACK.mkdir(parents=True,exist_ok=True);return [{"name":p.name,"size":p.stat().st_size,"modified":p.stat().st_mtime} for p in sorted(BACK.glob("*.zip"),key=lambda x:x.stat().st_mtime,reverse=True)]
