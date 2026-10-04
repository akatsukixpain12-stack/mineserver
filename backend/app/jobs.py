from __future__ import annotations
import asyncio,uuid
from dataclasses import dataclass,field
from datetime import datetime,timezone
@dataclass
class Job:
    id:str;server_id:str;kind:str;status:str="queued";progress:int=0;message:str="Queued";error:str|None=None;created_at:str=field(default_factory=lambda:datetime.now(timezone.utc).isoformat());result:dict=field(default_factory=dict)
class JobManager:
    def __init__(self):self.jobs={};self.listeners={}
    def create(self,server_id,kind):
        j=Job(uuid.uuid4().hex,server_id,kind);self.jobs[j.id]=j;self.listeners[j.id]=set();return j
    def update(self,j,**kw):
        for k,v in kw.items():setattr(j,k,v)
    def get(self,jid):return self.jobs.get(jid)
    async def stream(self,jid,ws):
        self.listeners.setdefault(jid,set()).add(ws)
        try:
            while True:
                j=self.jobs.get(jid)
                if not j:return
                await ws.send_json({"type":"job","job":j.__dict__})
                if j.status in {"complete","failed","cancelled"}:return
                await asyncio.sleep(.7)
        finally:self.listeners.get(jid,set()).discard(ws)
jobs=JobManager()
