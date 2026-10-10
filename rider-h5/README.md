# 骑手 H5（独立应用）

QiPay 骑手端移动应用：查看预计工资、月历、方案、奖惩、公告，并申请预支。不放在 FBA 前端仓库内。

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
| `.env.development` | `VITE_API_BASE` | 开发后端源，`http://127.0.0.1:8000` |
| `.env.production` | `VITE_API_BASE` | 同域相对路径 `/api`，由反向代理转发 |

接口路径仍写完整前缀：登录 `/api/v1/auth/*`，骑手端 `/api/v1/rider-salary/me/*`。生产 base 为 `/api` 时不会再拼成 `/api/api/v1/...`。

## 生产路径

`pnpm build` 的 Vite `base` 与 vue-router history base 为 `/rider-h5/`（同域子路径）。开发服务器不改，仍是 `http://localhost:5174/`。

Nginx 需要同时做到：

- `/api/` 反代到后端
- `/rider-h5/` 托管 `dist/`，未知路径回落到 `/rider-h5/index.html`，这样刷新 `/rider-h5/home` 等路由不会 404

生产页面与接口同域，不再依赖 CORS。开发仍跨源，CORS 配置见下。

## 后端 CORS

开发时 H5 与后端不同源，必须把 H5 origin 加入 `fastapi-best-architecture/backend/.env`（环境配置，不是框架源码）：

```
CORS_ALLOWED_ORIGINS='["http://127.0.0.1","http://localhost:5173","http://localhost:5174","http://127.0.0.1:5174"]'
```

`pydantic-settings` 会把 JSON 数组解析为 `list[str]`。改完后重启后端。不要改 `backend/core/conf.py`。开发时请用 `http://localhost:5174` 打开页面。

## 字体

首屏不再请求 Google Fonts。中文走系统字体栈（`system-ui`、苹方、微软雅黑、思源黑体等）。金额和单量用的数字字体是 **Barlow Condensed** 的自托管子集（字重 600 / 700，只含数字、正负号、小数点、千分位和空金额占位符），`font-variant-numeric: tabular-nums` 走字体里的等宽数字。页面未使用的 IBM Plex Mono 已去掉，等宽场景回退系统等宽栈。

字体文件在 `public/fonts/`，样式用相对路径 `./barlow-condensed-*.woff2`。`index.html` 通过 `%BASE_URL%fonts/barlow-condensed.css` 引入，开发 base `/` 和生产 base `/rider-h5/` 都能加载。

来源与许可：

- 字体：[Barlow](https://github.com/jpt/barlow)（The Barlow Project Authors，2017）
- 许可：SIL Open Font License 1.1，全文见 `public/fonts/OFL.txt`
- 版权声明未指定 Reserved Font Name，子集仍使用家族名 Barlow Condensed，并随仓库再分发

## 登录

骑手账号由站点开通，用户名=工号。验收账号示例：`D5A001` / `Rider@123456`。登录需图形验证码（`GET /api/v1/auth/captcha`）。
