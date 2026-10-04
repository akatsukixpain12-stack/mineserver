#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri_plugin_shell::ShellExt;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let autostart = std::env::var("MINESERVER_DESKTOP_AUTOSTART").unwrap_or_else(|_| "0".into());
            if autostart != "0" {
                match app.shell().sidecar("mineserver") {
                    Ok(command) => {
                        let _ = command.spawn();
                    }
                    Err(error) => eprintln!("Mineserver native core was not started: {error}"),
                }
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("failed to run Mineserver desktop app");
}
