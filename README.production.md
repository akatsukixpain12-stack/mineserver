# MineHub real runtime

This is the real control-plane implementation for Mineserver. It provisions actual Google Compute Engine VMs instead of simulating a terminal.

Browser -> FastAPI on Cloud Run -> Compute Engine VM -> Java Minecraft process.

Each VM gets a boot-time startup script, installs Java 21, downloads the selected server JAR, starts the MineHub agent and exposes Minecraft TCP/25565. The agent keeps an outbound WebSocket to the control plane, streams stdout, accepts console commands/power actions, and reports CPU/RAM/disk metrics.

Paper, Fabric and Vanilla are implemented. Forge/NeoForge are deliberately rejected until their installer lifecycle is implemented.

Modrinth search/version/download is server-side. CurseForge search/files are server-side and require a CurseForge API key kept in Secret Manager.

Cloud Run is only the control plane. Cloud Run WebSockets have a maximum request timeout of 60 minutes and need reconnect handling. Compute Engine supports VM startup scripts, which is how the runtime is bootstrapped.

## Deploy

1. Select a Google Cloud project and enable billing.
2. Enable Compute Engine, Cloud Run, Firestore, Artifact Registry and Secret Manager.
3. Create Firestore Native.
4. Create the minehub-admin-token and optionally curseforge-api-key secrets.
5. Give the Cloud Run service account permission to create/manage Compute Engine instances and read the secrets.
6. Build/deploy backend/ with scripts/deploy-gcp.sh.
7. Set CONTROL_URL to the Cloud Run HTTPS URL and redeploy. The VM agents then connect to wss://<cloud-run>/agent/ws.
8. Set `GOOGLE_CLIENT_ID` on Cloud Run and configure the Google OAuth application's Authorized JavaScript origins for the deployed web panel. Creating a server then creates a real VM.

## Security before public launch

Replace the single admin token with a real identity provider, add per-user quotas, add idle VM shutdown, use least-privilege service accounts, add Cloud Storage backups and add Pub/Sub/Redis fan-out if multiple Cloud Run instances must share live console sessions.
