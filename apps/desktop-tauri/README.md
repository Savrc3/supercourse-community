# Windows 轻量桌面端

正式轻量版复用 `apps/web`，应用 ID、安装名和 WebView2 数据来源均与旧 Electron 版及先前样例分开。它不会覆盖旧版本地数据；远程模式迁移时先清空旧版待传队列，再在新版登录同一服务器账号；本地模式需先导出备份再导入。Windows 2.0.2 已公开发布，提醒、实时同步和回退仍需按 Windows 验收指引安装检查。

## 开发与构建

需要 Node.js 24、Rust stable、Windows C++ Build Tools；运行安装后的程序还需要 WebView2 Runtime。安装包使用 WebView2 在线引导安装模式。

```sh
npm install
npm run dev --workspace @supercourse/desktop-tauri
npm run build:windows --workspace @supercourse/desktop-tauri
```

Windows NSIS 安装包输出到 `src-tauri/target/release/bundle/nsis/`。推送试验分支会运行「Windows 轻量版候选包」工作流，只上传构建产物；正式 `release.yml` 在标签发布时构建轻量版，旧 Electron 可由手动工作流构建回退。

历史 [样例 Windows CI 构建](https://github.com/Savrc3/supercourse/actions/runs/36314599247) 已成功：安装包 4,051,142 字节，SHA-256 `abf0c342eba1431521c1f39aaf60be15b891c4d0549106f67f58500d9342a652`。用户已验证样例基础功能；正式候选版新增能力仍需在 Windows 10/11 实测。

Tauri 模式不注册 PWA Service Worker，前端文件由安装包本地提供；托盘提供打开、更新页、自启开关和退出。API 访问使用 Tauri HTTP 插件的 HTTPS/本机白名单，SSE 由 Rust 原生客户端转发，从而避免改生产 API 的 CORS 配置。Windows 待办通知点击路由已实现，但须在已安装的正式候选包中验证。
