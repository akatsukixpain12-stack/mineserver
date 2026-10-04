from __future__ import annotations
import json,sqlite3,threading
from datetime import datetime,timezone
from typing import Any
from .config import settings
try: from google.cloud import firestore
except Exception: firestore=None
def utcnow(): return datetime.now(timezone.utc).isoformat()
class Store:
    def __init__(self):
        self._lock=threading.Lock();self._firestore=None
        if settings.project_id and firestore:
            try:self._firestore=firestore.Client(project=settings.project_id)
            except Exception:self._firestore=None
        self._db=None
        if self._firestore is None:
            self._db=sqlite3.connect(settings.local_db,check_same_thread=False);self._db.row_factory=sqlite3.Row
            self._db.execute("CREATE TABLE IF NOT EXISTS servers (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL)");self._db.commit()
    @property
    def persistent(self):return self._firestore is not None
    def put_server(self,data:dict[str,Any]):
        data=dict(data);data["updated_at"]=utcnow()
        if self._firestore:self._firestore.collection(settings.firestore_collection).document(data["id"]).set(data);return
        with self._lock:
            self._db.execute("INSERT INTO servers(id,owner_id,data,updated_at) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET owner_id=excluded.owner_id,data=excluded.data,updated_at=excluded.updated_at",(data["id"],data["owner_id"],json.dumps(data),data["updated_at"]));self._db.commit()
    def get_server(self,sid):
        if self._firestore:
            x=self._firestore.collection(settings.firestore_collection).document(sid).get();return x.to_dict() if x.exists else None
        x=self._db.execute("SELECT data FROM servers WHERE id=?",(sid,)).fetchone();return json.loads(x["data"]) if x else None
    def list_servers(self,owner_id=None,public_only=False):
        if self._firestore:
            q=self._firestore.collection(settings.firestore_collection)
            if owner_id:q=q.where("owner_id","==",owner_id)
            if public_only:q=q.where("public","==",True)
            return [x.to_dict() for x in q.stream()]
        sql="SELECT data FROM servers";p=[];c=[]
        if owner_id:c.append("owner_id=?");p.append(owner_id)
        if public_only:c.append("json_extract(data,'$.public')=1")
        if c:sql+=" WHERE "+" AND ".join(c)
        return [json.loads(x["data"]) for x in self._db.execute(sql,p).fetchall()]
    def update_server(self,sid,**changes):
        x=self.get_server(sid)
        if not x:raise KeyError(sid)
        x.update(changes);self.put_server(x);return x
    def delete_server(self,sid):
        if self._firestore:self._firestore.collection(settings.firestore_collection).document(sid).delete();return
        with self._lock:self._db.execute("DELETE FROM servers WHERE id=?",(sid,));self._db.commit()
store=Store()
