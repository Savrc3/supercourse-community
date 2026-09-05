# Docker Compose 自建

这是一个单用户实例：后端、SQLite 数据和媒体文件只服务部署者自己。它适合希望多设备同步、但不想使用他人服务器的人。

## 首次启动

1. 在项目根目录复制 `server/.env.example` 为 `server/.env`，设置随机的 `SC_SECRET_KEY` 和 `SC_DEVICE_TOKEN_SECRET`。
2. 首次启动保持 `SC_ALLOW_REGISTRATION=true`，创建唯一账号后立即改成 `false`，再重启 API。
3. 执行：

   ```powershell
   docker compose -f deploy/docker-compose.yml up -d --build
   ```

4. 打开 `http://localhost:8080`，选择“连接自己的服务器”，填写 `http://localhost:8080`。
5. 之后在 Android、Windows 或其他浏览器中填写同一个后端地址，并使用同一账号登录。

## 生产部署

请在外层反向代理提供 HTTPS，把 `SC_ALLOWED_ORIGINS` 改成实际前端来源，并保持 `SC_EXPOSE_HEALTH_DETAILS=false`。默认关闭 QQ 通知，只有部署者自己配置 OneBot 后才启用。

数据保存在 Docker 卷 `supercourse-data` 中。升级前执行 `docker compose ... down` 并备份该卷；不要把 `.env`、数据卷或备份提交到 Git。

## 停止与升级

```powershell
docker compose -f deploy/docker-compose.yml logs --tail=100 api
docker compose -f deploy/docker-compose.yml down
docker compose -f deploy/docker-compose.yml up -d --build
```

升级后检查首页、登录、课表读取和健康检查；健康检查只返回最小状态，不包含数据库大小或媒体目录等内部信息。
