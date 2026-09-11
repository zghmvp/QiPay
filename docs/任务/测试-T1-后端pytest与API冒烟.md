# T1｜后端 pytest 补测 + API 冒烟

## 必读
- `docs/设计/02-开发子角色通用守则.md`
- `docs/设计/00-架构决策纲要.md` §2/§3/§8/§10
- `docs/任务/待修复清单.md`（#2 时区、#13 预支发放后预估）
- `backend/plugin/rider_salary/tests/**`

## 目标
1. 全量 `uv run --python 3.12 pytest backend/plugin/rider_salary/tests -q` 必须全绿；若有失败，修测试或修实现（只动插件目录）。
2. 补测覆盖清单 #2：夜间加价时区——送达 23:05 Asia/Shanghai 命中、13:00 不命中（若已有同类用例则核对即可）。
3. 补测/curl 覆盖清单 #13：预支 mark-paid 后 draft+stale → `/me/payroll-estimate` 的 `is_estimate=true`。
4. API 冒烟（admin swagger 登录）：站点列表、订单导入模板、生成周期、算薪、日历、工作台、预支列表、订单导出、日标记 `is_locked`、payrolls?stale、plan-versions rollback 返回含 id。
5. 不改框架；不 destroy 现网库。最终把清单 #2/#13 状态改为「已验（T1）」或「失败」并说明。

## 交付
按守则 §8，≤30 行：测试数量、新增用例文件、冒烟结果表、清单更新。
