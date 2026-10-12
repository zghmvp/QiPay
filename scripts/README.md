# 验收脚本

`t2_acceptance.mjs` 覆盖管理端主要页面和骑手 H5。`ux_check.mjs` 覆盖管理端列表页，并在两个视口下截图。两者都：

- 用 `import.meta.url` 定位仓库，不写死本机家目录
- 从环境变量读账号密码；未设置时用下面的演示账号
- 走真实登录页，验证码用 Redis 的 `fba:login:captcha:<uuid>`（见 `docs/research/环境初始化记录.md` §4）
- 不调用 `/auth/login/swagger`
- 每个页面断言关键文本还在、地址正确、没有打到本机的 4xx/5xx
- 新建再删除一条草稿公告（标题前缀 `P111验收`），并核对接口状态是草稿、删除后列表里没有它
- 不修改 `D5A` / `D5B` 的周期和薪资单
- 断言失败时以非 0 退出

演示账号默认值（可用环境变量覆盖）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `QIPAY_ADMIN_USER` / `QIPAY_ADMIN_PASSWORD` | `admin` / `123456` | 管理端 |
| `QIPAY_RIDER_USER` / `QIPAY_RIDER_PASSWORD` | `D5A001` / `Rider@123456` | 骑手 H5，仅 `t2_acceptance.mjs` |
| `QIPAY_API_BASE` | `http://127.0.0.1:8000` | 后端 |
| `QIPAY_ADMIN_BASE` | `http://localhost:5173` | 管理端。后端默认 CORS 只放行这个源，不要改成 `127.0.0.1` |
| `QIPAY_H5_BASE` | `http://localhost:5174` | 骑手 H5。后端需放行该源，否则浏览器会拦截登录请求 |
| `QIPAY_SHOT_DIR` | `<仓库>/.runtime/acceptance/t2` 或 `ux` | 截图目录 |
| `QIPAY_MONTH` | `2026-09` | 工作台、日历、H5 日详情使用的月份 |
| `QIPAY_CAPTCHA_PREFIX` | `fba:login:captcha` | Redis 验证码前缀 |
| `QIPAY_REDIS_CLI` | `redis-cli` | 读验证码的命令 |

跑之前：后端 8000、管理端 5173 已启动；`t2_acceptance.mjs` 还需要骑手 H5 5174。PostgreSQL 和 Redis 也要在。登录接口大约每分钟 5 次，两个脚本请隔开跑，不要并发点登录。

```bash
node scripts/t2_acceptance.mjs
node scripts/ux_check.mjs
```

把某一页的期望文本改坏后，脚本应以非 0 退出。不必改页面，用环境变量演练：

```bash
QIPAY_BREAK_PAGE=工作台 QIPAY_BREAK_TEXT=不可能出现的验收文案 QIPAY_FAIL_FAST=1 \
  node scripts/t2_acceptance.mjs
```

`QIPAY_BREAK_PAGE` 是脚本里的页面名称（如 `工作台`、`H5首页`）。`QIPAY_FAIL_FAST=1` 时遇到第一项失败立即退出。
