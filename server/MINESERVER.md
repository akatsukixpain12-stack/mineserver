# Mineserver native server core

This directory contains the headless Rust Minecraft server core used by the Mineserver web hosting control plane.

It is derived from Pumpkin at commit `a8db585158ba109b4664eb755d7be76f20ac8f6b`. Upstream GPL-3.0 copyright and license notices remain in the source tree.

This core is **not a web UI**. The browser dashboard lives at the repository root and talks to the FastAPI control plane; the control plane provisions and supervises this native server process.

The executable package is named `mineserver`, and release builds produce `mineserver` / `mineserver.exe`.
