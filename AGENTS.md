# QiPay · 骑手薪资管理平台 — AI 开发入口

> 任何模型/开发者进入本仓库先读本文（约 3 分钟），再按「文档导航」读对应约定。本文只写不可违背的规则与索引，不写实现细节。

## 1. 项目是什么

面向即时配送站点的骑手薪资平台：导入订单明细 → 公式引擎按方案算薪 → 结算周期锁账/发薪 → 骑手 H5 查看与预支。三个可交付单元：

| 单元 | 路径 | 技术 | 端口 |
|---|---|---|---|
| 后端插件 | `fastapi-best-architecture/backend/plugin/rider_salary/` | FBA 应用级插件（FastAPI + SQLAlchemy 2 + PostgreSQL） | 8000 |
| 管理端前端插件 | `fastapi-best-architecture-ui/apps/web-antdv-next/src/plugins/rider-salary/` | FBA 前端插件（Vue 3 + Vben + Antdv Next + VxeTable） | 5173 |
| 骑手 H5 | `rider-h5/` | 独立 Vue 3 + Vite + Vant 4 + Pinia | 5174 |

其余目录：`docs/` 设计/约定/任务/验收，`scripts/` 启停与验收脚本，`.runtime/` PID 与日志，`fastapi_best_architecture_docs/` 与 `llms.txt` 为 FBA 官方文档镜像（只读）。

## 2. 硬性规则（违反即缺陷）

1. **禁改 FBA 框架代码。** 后端只能改 `backend/plugin/rider_salary/**`；前端只能改 `src/plugins/rider-salary/**`。唯一例外：`fastapi-best-architecture/backend/.env`（环境配置，可追加 CORS 等运行参数）。`rider-h5/` 是自有应用，可自由改。确需改框架 → 停止该项，在回复中以「⚠️ 需用户授权的框架修改申请」列出文件、原因、影响、替代方案。
2. **全中文可见文本，代码标识符英文。** 接口 summary/description、Pydantic description、SQL COMMENT、异常 msg、日志、导出表头、界面文字全部中文；前端不用 `$t()`/langs。表前缀 `rs_`，权限码前缀 `rs:`，模型类前缀 `RiderSalary`，路由前缀 `/rider-salary`，API 前缀 `/api/v1/rider-salary`。公式引擎字段/函数/运算符用中文。
3. **管理端页面路由由数据库 `sys_menu` 决定，不是前端 `routes/index.ts`。** 新增页面（含隐藏详情页）必须在 4 份 `sql/*/init*.sql` 增加菜单行并绑定角色，且给现网库执行增量 SQL（放 `sql/patch/`），否则 404。见 `docs/约定/02-管理端前端约定.md` §1。
4. **影响算薪的写操作三件套**：写前 `assert_not_locked`（锁账校验）→ 写后 `mark_stale`（重算标记）→ `audit_service.record`（审计，带 before/after 快照）。涉及 `rs_order` / `rs_adjustment` / `rs_rider_plan_binding` / `rs_day_flag` / `rs_rider_employ_history` 的写操作一律遵守。
5. **不做 git add/commit/push**，除非用户明确要求。不删除/重建 FBA 系统表；插件表可用 `destroy.sql` 重建。

## 3. 快速开始

```bash
# 启停（后端 8000、管理端 5173、H5 5174；日志在 .runtime/logs/）
/Users/zghmvp/Desktop/QiPay/scripts/start_all.sh
/Users/zghmvp/Desktop/QiPay/scripts/stop_all.sh

# 数据库：127.0.0.1:5432  用户 root / 密码 postgres  库 fba（PostgreSQL，自增主键）
PGPASSWORD=postgres psql -h 127.0.0.1 -U root -d fba

# 后端测试 / 格式（在 fastapi-best-architecture 目录）
uv run --python 3.12 pytest backend/plugin/rider_salary/tests -q
uv run ruff check backend/plugin/rider_salary && uv run ruff format backend/plugin/rider_salary

# 前端类型检查（在 apps/web-antdv-next 目录，只看插件报错）
npx vue-tsc --noEmit -p tsconfig.json 2>&1 | rg "rider-salary"
```

账号：管理端 `admin / 123456`（超管）；站点负责人 `site_owner_d2 / Rider@123456`；骑手 H5 `D5A001 / Rider@123456`。登录需验证码，取法见 `docs/research/环境初始化记录.md` §4。Swagger：`http://127.0.0.1:8000/docs`。

## 4. 文档导航（按问题找文档）

| 我要… | 读 |
|---|---|
| 了解规则全貌、约定文档索引 | `docs/约定/README.md` |
| 写/改后端接口、模型、Service、CRUD、SQL 种子、测试 | `docs/约定/01-后端开发约定.md` |
| 写/改管理端页面、表格、表单、抽屉、权限、路由 | `docs/约定/02-管理端前端约定.md` |
| 写/改骑手 H5 | `docs/约定/03-骑手H5约定.md` |
| 搞清 20 张表怎么关联、状态机、算薪三阶段、术语 | `docs/约定/04-领域模型与术语.md` |
| 端到端新增一个模块/页面/接口/字段/权限码 | `docs/约定/05-新增功能端到端清单.md` |
| 避免重复踩坑 | `docs/约定/06-踩坑记录.md` |
| 字段级规格与业务决策（唯一规格源） | `docs/设计/00-架构决策纲要.md`（§10 决策补遗优先） |
| 产品交互与页面清单 | `docs/设计/01-产品方案.md` |
| 后端骨架签名（工具函数、路由前缀、菜单 ID 段） | `docs/设计/03-后端骨架说明.md` |
| 薪资方案配置算例 | `docs/设计/04-薪资方案案例库.md`；前端内置案例在 `constants/plan-presets.ts` |
| 环境、端口、启停、验证码、重置库 | `docs/research/环境初始化记录.md` |
| 历史问题与状态 | `docs/任务/待修复清单.md` |
| FBA 框架本身怎么用 | `.agents/skills/fba/SKILL.md`；`llms.txt`；`fastapi_best_architecture_docs/` |
| Antdv Next 组件 API | `.agents/skills/antdv-next/SKILL.md` |

优先级冲突时：用户当前指令 > 本文 > `docs/约定/*` > `00-架构决策纲要` > `01-产品方案` > 调研文档。

## 5. 完成定义（每次交付前自检）

- 后端：`ruff check/format` 通过；pytest 全绿；重启后端 `/docs` 出现新接口；curl 走通一条主路径。
- 前端：`vue-tsc` 无插件内报错；dev server 无编译错误；页面能打开且主流程可操作（能截图更好）。
- 新页面：4 份 init SQL + `sql/patch/` 增量 SQL 均已更新，且已对现网库执行。
- 回复必含：① 改动文件清单 ② 验证方式与结果 ③ 已知问题 ④ 需用户决策的问题 ⑤ 框架修改申请（若有）。
- 临时脚本/文件不留在仓库（放 `/tmp`）。
