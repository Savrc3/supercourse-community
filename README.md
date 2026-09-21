# 课序 · 个人课表与学习事务管理

一个本地优先的大学课表 + 课程待办小工具。它支持 Web/PWA、Android 和 Windows 三端：不想部署服务器时可以只在当前设备使用；需要多设备同步时，可以连接自己部署的后端。

本项目的定位是一个可自行带走、运行和修改的开源工具，不是公共 SaaS，也不提供维护者的个人服务器作为默认后端。使用者可以把它当作本地课表，也可以按文档部署自己的同步服务；公开版本不承诺持续在线服务或长期兼容维护。

## 作者说明

作者是集成电路方向的在读学生，不是专业软件工程师。本项目主要为解决个人需求，在 AI 辅助下完成设计、实现、测试和文档整理；文档描述的是当前已经验证的范围，不代表商业软件级保证。欢迎把它当作一个真实的学习实践，也欢迎通过 Issue 指出问题。

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

Windows：

```powershell
powershell -NoProfile -File scripts/setup-env.ps1
cd server; uv sync; cd ..
npm ci
npm run dev
```

Linux / WSL：

```bash
bash scripts/setup-env.sh        # 用户级安装 JDK 21 + Android SDK + uv + Python 3.10.12
cd server && uv sync && cd ..
npm ci
npm run dev
```

`npm run dev` 按平台自动分流（Windows → `scripts/dev.ps1`，Linux/macOS → `scripts/dev.sh`）。然后打开 `http://127.0.0.1:5173`。若 4173 已被 Windows 桌面端占用，开发前端仍使用 5173；Playwright 会自动使用独立的 4174 测试端口。

## 构建三端

```powershell
npm run build --workspace @supercourse/web
npm run build --workspace @supercourse/desktop
npm run android:release --workspace @supercourse/mobile
```

Windows 安装包在 `apps/desktop/dist/`；Android Release APK 由脚本输出到 Android 构建目录。正式签名材料只保存在本机受保护目录，不进入仓库。

## 质量门禁

```bash
npm run check-all          # Windows → check-all.ps1；Linux/WSL → check-all.sh
```

门禁包含后端 pytest/ruff/mypy、前端 ESLint/vue-tsc/Vitest/build、Playwright 冒烟和敏感信息扫描。发布前还要完成 [安全与兼容性验收清单](安全与兼容性验收清单.md)。

## 文档入口

- [使用与恢复手册](docs/使用与恢复手册.md)：日常使用、备份和恢复。
- [零基础项目解剖课](docs/课序项目·零基础解剖课.md)：从一次点击开始理解项目的结构、数据流和技术实现。
- [自建部署手册](deploy/README.md)：Docker Compose 单实例部署。
- [隐私与运行模式说明](docs/隐私与运行模式说明.md)：本地、自建和个人实例的边界。
- [贡献指南](CONTRIBUTING.md) 与 [安全政策](SECURITY.md)。
- [需求规格说明书](docs/需求规格说明书.md)、[技术方案设计](docs/技术方案设计.md)、[交接开发手册](docs/交接开发手册.md)。
- [代码审查报告](docs/代码审查报告.md)：已知缺陷、复现证据与修复优先级。

## 许可

本项目使用 MIT License，见 [LICENSE](LICENSE)。公开发布时只发布经过脱敏的源码和示例配置，不发布个人实例、数据库、日志、真实教务文件、密钥或个人通知配置。
