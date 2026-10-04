# MineHub control plane

Minecraft worlds and the Java process live on Compute Engine. Firestore stores server metadata. Cloud Run is the HTTP/WebSocket control plane.

Lifecycle:
POST /api/servers -> resolve server binary -> create VM -> startup script -> Java/agent -> Minecraft.
Console: browser WebSocket -> Cloud Run -> authenticated agent -> Java stdin/stdout.
Install: provider API -> compatible artifact -> authenticated agent -> backup -> download -> restart.
Metrics: agent samples CPU/RAM/disk and sends player join/leave state.

CurseForge credentials remain server-side. Agent tokens are server-specific and never returned by API responses.
