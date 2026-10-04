#!/usr/bin/env bash
set -euo pipefail
cargo build --release --manifest-path server/Cargo.toml -p mineserver
mkdir -p bin
cp -f server/target/release/mineserver bin/mineserver
