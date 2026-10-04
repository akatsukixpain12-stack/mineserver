$ErrorActionPreference = "Stop"
cargo build --release --manifest-path server/Cargo.toml -p mineserver
New-Item -ItemType Directory -Force bin | Out-Null
Copy-Item server/target/release/mineserver.exe bin/mineserver.exe -Force
