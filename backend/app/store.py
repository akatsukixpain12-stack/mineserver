from __future__ import annotations
import json,sqlite3,threading
from datetime import datetime,timezone
from typing import Any
from .config import settings
try:
    from google.cloud import firestore
except Exception:
    firestore=None

def utcnow():
    return datetime.now(timezone.utc).isoformat()

class Store:
    def __init__(self):
        self._lock=threading.Lock()
        self._firestore=None
        if settings.project_id and firestore:
            try:
                self._firestore=firestore.Client(project=settings.project_id)
            except Exception:
                self._firestore=None
        self._db=None
        if self._firestore is None:
            self._db=sqlite3.connect(settings.local_db,check_same_thread=False)
            self._db.row_factory=sqlite3.Row
            self._db.execute("CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL)")
            self._db.execute("CREATE TABLE IF NOT EXISTS servers (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL)")
            self._db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, server_id TEXT, data TEXT NOT NULL, updated_at TEXT NOT NULL)")
            self._db.commit()

    @property
    def persistent(self):
        return self._firestore is not None

    def upsert_user(self,user:dict[str,Any]):
        data=dict(user)
        data["updated_at"]=utcnow()
        if self._firestore:
            self._firestore.collection("users").document(data["id"]).set(data,merge=True)
            return
        with self._lock:
            self._db.execute(
                "INSERT INTO users(id,data,updated_at) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at",
                (data["id"],json.dumps(data),data["updated_at"]),
            )
            self._db.commit()

    def put_server(self,data:dict[str,Any]):
        data=dict(data);data["updated_at"]=utcnow()
        if self._firestore:
            self._firestore.collection(settings.firestore_collection).document(data["id"]).set(data,merge=True)
            return
        with self._lock:
            self._db.execute(
                "INSERT INTO servers(id,owner_id,data,updated_at) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET owner_id=excluded.owner_id,data=excluded.data,updated_at=excluded.updated_at",
                (data["id"],data["owner_id"],json.dumps(data),data["updated_at"]),
            )
            self._db.commit()

    def get_server(self,sid):
        if self._firestore:
            x=self._firestore.collection(settings.firestore_collection).document(sid).get()
            return x.to_dict() if x.exists else None
        x=self._db.execute("SELECT data FROM servers WHERE id=?",(sid,)).fetchone()
        return json.loads(x["data"]) if x else None

    def list_servers(self,owner_id=None,public_only=False):
        if self._firestore:
            q=self._firestore.collection(settings.firestore_collection)
            if owner_id:
                q=q.where("owner_id","==",owner_id)
            if public_only:
                q=q.where("public","==",True)
            return [x.to_dict() for x in q.stream()]
        sql="SELECT data FROM servers";params=[];clauses=[]
        if owner_id:
            clauses.append("owner_id=?");params.append(owner_id)
        if public_only:
            clauses.append("json_extract(data,'$.public')=1")
        if clauses:
            sql+=" WHERE "+" AND ".join(clauses)
        rows=self._db.execute(sql,params).fetchall()
        return [json.loads(x["data"]) for x in rows]

    def update_server(self,sid,**changes):
        x=self.get_server(sid)
        if not x:
            raise KeyError(sid)
        x.update(changes)
        self.put_server(x)
        return x

    def put_schedule(self,data:dict[str,Any]):
        data=dict(data);data["updated_at"]=utcnow()
        if self._firestore:
            self._firestore.collection("mineserver_schedules").document(data["id"]).set(data,merge=True)
            return
        with self._lock:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS schedules (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, server_id TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            self._db.execute(
                "INSERT INTO schedules(id,owner_id,server_id,data,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at",
                (data["id"],data["owner_id"],data["server_id"],json.dumps(data),data["updated_at"]),
            )
            self._db.commit()

    def get_schedule(self,sid):
        if self._firestore:
            x=self._firestore.collection("mineserver_schedules").document(sid).get()
            return x.to_dict() if x.exists else None
        self._db.execute("CREATE TABLE IF NOT EXISTS schedules (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, server_id TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL)")
        x=self._db.execute("SELECT data FROM schedules WHERE id=?",(sid,)).fetchone()
        return json.loads(x["data"]) if x else None

    def list_schedules(self,owner_id=None,server_id=None):
        if self._firestore:
            q=self._firestore.collection("mineserver_schedules")
            rows=[x.to_dict() for x in q.stream()]
            return [x for x in rows if (not owner_id or x.get("owner_id")==owner_id) and (not server_id or x.get("server_id")==server_id)]
        self._db.execute("CREATE TABLE IF NOT EXISTS schedules (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, server_id TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL)")
        clauses=[];params=[]
        if owner_id:clauses.append("owner_id=?");params.append(owner_id)
        if server_id:clauses.append("server_id=?");params.append(server_id)
        sql="SELECT data FROM schedules"+((" WHERE "+" AND ".join(clauses)) if clauses else "")
        return [json.loads(x["data"]) for x in self._db.execute(sql,params).fetchall()]

    def delete_schedule(self,sid):
        if self._firestore:
            self._firestore.collection("mineserver_schedules").document(sid).delete()
            return
        self._db.execute("CREATE TABLE IF NOT EXISTS schedules (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, server_id TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL)")
        with self._lock:self._db.execute("DELETE FROM schedules WHERE id=?",(sid,));self._db.commit()

    def delete_server(self,sid):

        if self._firestore:
            self._firestore.collection(settings.firestore_collection).document(sid).delete()
            return
        with self._lock:
            self._db.execute("DELETE FROM servers WHERE id=?",(sid,))
            self._db.commit()

store=Store()