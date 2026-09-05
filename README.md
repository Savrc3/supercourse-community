# 超课表（Supercourse）

一个本地优先的大学课表 + 课程待办应用。它支持 Web/PWA、Android 和 Windows 三端：不想部署服务器时可以只在当前设备使用；需要多设备同步时，可以连接自己部署的后端。

## 选择一种使用方式

### 只在本机使用

直接打开 Web/PWA、Android 或 Windows 应用，首次启动选择“本地使用”。课程、待办、图片和设置只保存在当前设备，不需要账号，也不会连接任何默认服务器。管理页提供本地备份导出与恢复。

### 使用自己的服务器同步

启动自己的 FastAPI + SQLite 服务，在应用首次启动时选择“连接自己的服务器”，填入服务器地址，再用同一个账号登录各端。服务端是同步真相源，客户端支持本地优先、断网写入和 outbox 重试。

最简单的自建方式见 [deploy/README.md](deploy/README.md)。

## 功能

- 周课表与单日课表：五个时间段、课程颜色、长名称换行、停课/调课/换教室。
- 课程管理：学期、课程资料、课程详情、教务 `.xls/.xlsx` 导入。
- 课程待办：标题、课程、截止日期/时间、优先级、标签、完成状态、提醒开关。
- 待办详情：富文本、清单、链接、图片和附件，支持离线缓存。
- 时间线、提醒、回收站、搜索、冲突箱和设备管理。
- 本地模式与自建服务器模式可以在启动向导中切换。

## 五分钟本地开发

```powershell
powershell -NoProfile -File scripts/setup-env.ps1
cd server; uv sync; cd ..
npm ci
powershell -NoProfile -File scripts/dev.ps1
```

然后打开 `http://localhost:5173`。若 4173 已被 Windows 桌面端占用，开发前端仍使用 5173；Playwright 会自动使用独立的 4174 测试端口。

## 构建三端

```powershell
npm run build --workspace @supercourse/web
npm run build --workspace @supercourse/desktop
npm run android:release --workspace @supercourse/mobile
```

Windows 安装包在 `apps/desktop/dist/`；Android Release APK 由脚本输出到 Android 构建目录。正式签名材料只保存在本机受保护目录，不进入仓库。

## 质量门禁

```powershell
powershell -NoProfile -File scripts/check-all.ps1
```

门禁包含后端 pytest/ruff/mypy、前端 ESLint/vue-tsc/Vitest/build、Playwright 冒烟和敏感信息扫描。发布前还要完成 [安全与兼容性验收清单](安全与兼容性验收清单.md)。

## 文档入口

- [使用与恢复手册](docs/使用与恢复手册.md)：日常使用、备份和恢复。
- [自建部署手册](deploy/README.md)：Docker Compose 单实例部署。
- [隐私与运行模式说明](docs/隐私与运行模式说明.md)：本地、自建和个人实例的边界。
- [贡献指南](CONTRIBUTING.md) 与 [安全政策](SECURITY.md)。
- [需求规格说明书](docs/需求规格说明书.md)、[技术方案设计](docs/技术方案设计.md)、[交接开发手册](docs/交接开发手册.md)。

## 许可

本项目使用 MIT License，见 [LICENSE](LICENSE)。公开发布时只发布经过脱敏的源码和示例配置，不发布个人实例、数据库、日志、真实教务文件、密钥或个人通知配置。
