$ErrorActionPreference = "Stop"
cargo build --release --manifest-path server/Cargo.toml -p pumpkin
New-Item -ItemType Directory -Force bin | Out-Null
Copy-Item server/target/release/pumpkin.exe bin/mineserver.exe -Force
