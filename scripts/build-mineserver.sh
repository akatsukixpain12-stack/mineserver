#!/usr/bin/env bash
set -euo pipefail
cargo build --release --manifest-path server/Cargo.toml -p pumpkin
mkdir -p bin
cp -f server/target/release/pumpkin bin/mineserver
