use std::sync::Mutex;
use std::time::Duration;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt as AutostartManagerExt};

#[derive(Default)]
struct EventRelay(Mutex<Option<tauri::async_runtime::JoinHandle<()>>>);

#[tauri::command]
fn desktop_stop_events(relay: tauri::State<'_, EventRelay>) {
    if let Some(task) = relay.0.lock().expect("event relay lock").take() {
        task.abort();
    }
}

#[tauri::command]
fn desktop_start_events(
    app: AppHandle,
    relay: tauri::State<'_, EventRelay>,
    base_url: String,
    token: String,
) -> Result<(), String> {
    if token.is_empty() {
        return Err("missing sync token".into());
    }
    let mut url = reqwest::Url::parse(&base_url).map_err(|error| error.to_string())?;
    let local = matches!(url.host_str(), Some("localhost" | "127.0.0.1"));
    if url.scheme() != "https" && !(url.scheme() == "http" && local) {
        return Err("sync events require HTTPS or localhost".into());
    }
    if url.username() != "" || url.password().is_some() || url.fragment().is_some() {
        return Err("invalid sync base URL".into());
    }
    url.set_path(&format!("{}/events", url.path().trim_end_matches('/')));
    url.query_pairs_mut().clear().append_pair("token", &token);
    let mut current = relay.0.lock().map_err(|error| error.to_string())?;
    if let Some(task) = current.take() {
        task.abort();
    }
    *current = Some(tauri::async_runtime::spawn(async move {
        let client = reqwest::Client::new();
        loop {
            if let Ok(mut response) = client.get(url.clone()).send().await {
                if response.status() == reqwest::StatusCode::UNAUTHORIZED {
                    break;
                }
                if response.status().is_success() {
                    let mut pending = Vec::new();
                    let mut event = String::new();
                    while let Ok(Some(chunk)) = response.chunk().await {
                        pending.extend_from_slice(&chunk);
                        while let Some(end) = pending.iter().position(|byte| *byte == b'\n') {
                            let line = pending.drain(..=end).collect::<Vec<_>>();
                            let line = String::from_utf8_lossy(&line);
                            let line = line.trim_end_matches(['\r', '\n']);
                            if let Some(value) = line.strip_prefix("event:") {
                                event = value.trim().to_owned();
                            } else if line.is_empty() {
                                if event == "change" || event == "hello" {
                                    let _ = app.emit("desktop-sync-event", event.clone());
                                }
                                event.clear();
                            }
                        }
                        if pending.len() > 8192 {
                            pending.clear();
                            event.clear();
                        }
                    }
                }
            }
            tokio::time::sleep(Duration::from_secs(5)).await;
        }
    }));
    Ok(())
}

fn reveal(app: &AppHandle, route: Option<&str>) {
    if let Some(window) = app.get_webview_window("main") {
        if let Some(path) = route {
            let _ = app.emit("desktop-navigate", path.to_owned());
        }
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

#[tauri::command]
fn desktop_show_main(app: AppHandle, path: Option<String>) {
    reveal(&app, path.as_deref());
}

#[tauri::command]
fn desktop_notify(
    app: AppHandle,
    title: String,
    body: String,
    todo_id: Option<String>,
) -> Result<(), String> {
    #[cfg(windows)]
    {
        let mut notification = notify_rust::Notification::new();
        notification
            .app_id(&app.config().identifier)
            .summary(&title)
            .body(&body);
        let handle = notification.show().map_err(|error| error.to_string())?;
        std::thread::spawn(move || {
            handle.wait_for_action(|action| {
                if action == "default" {
                    let route = todo_id
                        .as_deref()
                        .filter(|id| {
                            !id.is_empty()
                                && id.chars().all(|c| c.is_ascii_alphanumeric() || c == '-')
                        })
                        .map(|id| format!("/todo/{id}"));
                    reveal(&app, route.as_deref());
                }
            });
        });
        Ok(())
    }
    #[cfg(not(windows))]
    {
        let _ = (app, title, body, todo_id);
        Err("系统通知仅支持 Windows 安装版".into())
    }
}

fn build_tray(app: &tauri::App) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, "open", "打开课序轻量版", true, None::<&str>)?;
    let update = MenuItem::with_id(app, "update", "检查更新", true, None::<&str>)?;
    let autostart_on =
        MenuItem::with_id(app, "autostart-on", "开机自启：开启", true, None::<&str>)?;
    let autostart_off =
        MenuItem::with_id(app, "autostart-off", "开机自启：关闭", true, None::<&str>)?;
    let separator_before = PredefinedMenuItem::separator(app)?;
    let separator_after = PredefinedMenuItem::separator(app)?;
    let quit = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
    let menu = Menu::with_items(
        app,
        &[
            &open,
            &update,
            &separator_before,
            &autostart_on,
            &autostart_off,
            &separator_after,
            &quit,
        ],
    )?;

    TrayIconBuilder::new()
        .tooltip("课序轻量版")
        .icon(
            app.default_window_icon()
                .expect("configured app icon")
                .clone(),
        )
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "open" => reveal(app, None),
            "update" => reveal(app, Some("/profile")),
            "autostart-on" => {
                let _ = app.autolaunch().enable();
            }
            "autostart-off" => {
                let _ = app.autolaunch().disable();
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                reveal(tray.app_handle(), None);
            }
        })
        .build(app)?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, args, _cwd| {
            let route = args
                .iter()
                .any(|arg| arg == "--settings")
                .then_some("/profile");
            reveal(app, route);
        }))
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec!["--hidden"]),
        ))
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .invoke_handler(tauri::generate_handler![
            desktop_show_main,
            desktop_notify,
            desktop_start_events,
            desktop_stop_events
        ]);

    builder
        .setup(|app| {
            app.manage(EventRelay::default());
            build_tray(app)?;
            if std::env::args().any(|arg| arg == "--hidden") {
                if let Some(window) = app.get_webview_window("main") {
                    window.hide()?;
                }
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .run(tauri::generate_context!())
        .expect("failed to run the Tauri desktop app");
}
