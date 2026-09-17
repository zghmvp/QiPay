# 骑手 H5（独立应用）

QiPay 骑手端移动应用：查看预计工资、月历、方案、奖惩，并申请预支。不放在 FBA 前端仓库内。

## 启动

```bash
cd /Users/zghmvp/Desktop/QiPay/rider-h5
pnpm install
pnpm dev
```

也可由仓库脚本一并拉起：

```bash
/Users/zghmvp/Desktop/QiPay/scripts/start_all.sh
/Users/zghmvp/Desktop/QiPay/scripts/stop_all.sh
```

- 本地地址：`http://localhost:5174/`（桌面预览会居中，最大宽度 480px）
- 端口固定 **5174**（`vite.config.ts` `server.port`）
- PID / 日志：`QiPay/.runtime/rider-h5.pid`、`QiPay/.runtime/logs/rider-h5.log`

## 环境变量

| 文件 | 变量 | 说明 |
|---|---|---|
| `.env.development` / `.env.production` | `VITE_API_BASE` | 后端根地址，默认 `http://127.0.0.1:8000` |

接口前缀：登录 `/api/v1/auth/*`，骑手端 `/api/v1/rider-salary/me/*`。

## 后端 CORS

H5 与后端不同源，必须把 H5 origin 加入 `fastapi-best-architecture/backend/.env`（环境配置，不是框架源码）：

```
CORS_ALLOWED_ORIGINS='["http://127.0.0.1","http://localhost:5173","http://localhost:5174","http://127.0.0.1:5174"]'
```

`pydantic-settings` 会把 JSON 数组解析为 `list[str]`。改完后重启后端。不要改 `backend/core/conf.py`。开发时请用 `http://localhost:5174` 打开页面。

## 登录

骑手账号由站点开通，用户名=工号。验收账号示例：`D5A001` / `Rider@123456`。登录需图形验证码（`GET /api/v1/auth/captcha`）。
