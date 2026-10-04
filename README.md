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
   - passwordless workspace/session API
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

Run the real FastAPI control plane locally:

- Windows PowerShell: `./scripts/run-local.ps1`
- Linux/macOS: `./scripts/run-local.sh`
- Open `http://127.0.0.1:8080`

The local process is the actual API/UI; it does not create fake servers or fake players. Creating a Minecraft runtime still requires the configured Google Compute Engine credentials because the real game process runs on a VM.

## Architecture direction — Pumpkin-inspired, web-based

MineHub is intentionally **not a copy of Pumpkin's UI or source**. Pumpkin is a native Rust Minecraft server focused on performance, protocol/game implementation, and a small runtime footprint. MineHub uses that same "real runtime, no fake dashboard" philosophy but exposes it through a web control plane.

### Version strategy

The control plane now discovers versions dynamically instead of hard-coding a handful of versions:

- **Vanilla:** Mojang's version manifest.
- **Paper / Folia / Purpur:** PaperMC project/build APIs.
- **Fabric:** Fabric Meta API.
- **Quilt:** Quilt Meta API.
- **Forge / NeoForge:** Maven metadata.
- The create-server UI displays the full discovered list for the selected runtime, so the catalog can grow with Minecraft releases without another frontend edit.

The important distinction is that a version appearing in the catalog is not a claim that every third-party runtime supports every historical Minecraft release. The backend asks the upstream runtime for the exact build before provisioning.

### No fake state

The production UI does not manufacture:

- player usernames
- online counts
- CPU/RAM/disk numbers
- server cards
- public server addresses
- console lines

Those values come from Google Compute Engine + the MineHub agent + the persistent server store. If there is no runtime, the UI shows an empty state.

### Modpacks

Modrinth .mrpack installs are handled server-side: the agent reads modrinth.index.json, skips files marked server-unsupported, downloads referenced files, verifies the supplied hashes, and applies overrides and server-overrides.

### Runtime architecture

**Browser → Cloud Run/FastAPI → Compute Engine Minecraft VM**

Cloud Run is the web/control layer; Minecraft itself runs on Compute Engine because a normal Cloud Run service is not a raw Minecraft TCP server. The control plane uses a browser-generated anonymous workspace ID instead of a forced login, then handles server provisioning, live WebSocket console traffic, provider APIs, metrics, files and the public directory.


## Current runtime integration

- **No pre-login:** the dashboard opens directly and creates a random local workspace ID in the browser. There is no fake account, fake avatar, fake email, or fake player list.
- **Real runtime:** Minecraft processes run on the provisioned Compute Engine VM, not inside the browser or as fake UI state.
- **Pumpkin:** the repository contains `vendor/Pumpkin` as a Git submodule pinned to the upstream Pumpkin source commit. The panel also exposes Pumpkin as a native runtime and downloads the matching official Linux release at provisioning time.
- Pumpkin is GPL-3.0 licensed; keep the upstream license/attribution when distributing the submodule or derivative work.
- The current upstream Pumpkin release is a native Rust server targeting Minecraft 26.3, so it is offered separately from the multi-version Java runtime catalog rather than pretending Pumpkin supports every Minecraft release.
