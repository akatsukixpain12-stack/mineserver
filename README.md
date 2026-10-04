# MineHub

A polished Minecraft hosting control-panel frontend for **Mineserver**.

## What is implemented

- Bouncy, modern dark Minecraft-hosting UI inspired by the useful patterns found in Minefort, Pterodactyl and modern commercial game panels — but deliberately not a pixel-for-pixel clone.
- Server dashboard with online player count, CPU/RAM/storage cards, IP/address card and power controls.
- Dedicated real-time terminal view with command input.
- Mods & Plugins marketplace UI with **Modrinth** and **CurseForge** source filters and one-click install actions.
- File manager, player list and server settings views.
- Create-server modal with region, software, Minecraft version and optional modpack.
- Responsive desktop/mobile layout.
- Frontend is designed so the demo data can be replaced by API/WebSocket data without redesigning the UI.

## Important production architecture

Do **not** run the actual Minecraft Java server as a normal Cloud Run service and advertise it as a raw Minecraft endpoint. Cloud Run services are HTTP/WebSocket/gRPC-oriented; a Minecraft server needs a game TCP endpoint. Cloud Run WebSockets also have request timeouts and require reconnect/synchronization handling.

Recommended Google Cloud architecture:

1. **Cloud Run — control plane**
   - authentication/session API
   - server create/start/stop/restart API
   - Modrinth/CurseForge proxy
   - console WebSocket gateway
   - metrics API
   - server discovery/join API
2. **Google Compute Engine or GKE — game runtime**
   - isolated Minecraft runtime per active server
   - Paper / Fabric / NeoForge / Vanilla
   - persistent world disk
   - Minecraft TCP port
3. **Cloud Storage**
   - backups, world archives and large artifacts
4. **Firestore**
   - users, servers, permissions, server metadata and job state
5. **Pub/Sub**
   - provisioning jobs, install queues and cross-instance events
6. **Optional Memorystore/Redis**
   - fan-out for console and live metrics when multiple Cloud Run instances are serving the same dashboard

This keeps the control plane scalable and inexpensive while putting the actual game process on infrastructure that can expose the Minecraft network port.

## One-click Modrinth / CurseForge flow

The UI intentionally calls the backend rather than exposing credentials in browser JavaScript.

Suggested endpoints:

- `GET /api/catalog/modrinth/search?q=&type=mod|modpack&mc=1.21.10&loader=fabric`
- `GET /api/catalog/curseforge/search?q=&type=mod|modpack&mc=1.21.10&loader=forge`
- `POST /api/servers/:id/install`
- `GET /api/servers/:id/install/:jobId`
- `WS /api/servers/:id/console`
- `GET /api/servers/:id/stats`
- `POST /api/servers`

For CurseForge, keep the API key server-side. Modrinth's public API exposes project search/version metadata, but a backend proxy is still preferable so compatibility logic and rate handling stay centralized.

The installer should:

1. Validate Minecraft version + loader.
2. Resolve the selected project/version.
3. Resolve required dependencies.
4. Download files to the correct `mods/` or `plugins/` directory.
5. Create a backup before destructive changes.
6. Stop/restart the game server when required.
7. Stream progress to the console/install queue.
8. Mark the installation complete only after the server reports healthy.

## Sources researched

- Minefort: console, plugins, file management and server-management UX.
- Pterodactyl: live console, resource statistics, power controls and server management patterns.
- BisectHosting Games Panel: one-click modpack/plugin installation and performance metrics.
- Modrinth API: project/modpack search and version metadata.
- CurseForge API: authenticated Minecraft catalog access.
- Google Cloud Run: WebSockets, request timeouts, stateless scaling and long-lived instance options.

## Development

This repository currently contains a static frontend prototype. Replace the demo functions in `index.html` with calls to the production API described above.
