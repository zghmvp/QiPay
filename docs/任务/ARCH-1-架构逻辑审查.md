# ARCH-1｜架构与业务逻辑审查

## 必读
- `docs/设计/00-架构决策纲要.md`（全文，尤其 §2–§4、§8、§10）
- `docs/设计/01-产品方案.md` 第 1、3、4、6、8 章
- `docs/设计/03-后端骨架说明.md`
- `docs/任务/待修复清单.md`
- 后端插件源码：`backend/plugin/rider_salary/service/**`、`engine/**`、`utils/**`

## 任务
1. **对照审查**：纲要/产品方案 vs 实际实现，列出逻辑不一致、遗漏边界、状态机漏洞、权限缺口、金额/时区/锁账/预支/反冲/方案不可变等高风险点。
2. **实码走读**：重点 calc_pipeline、period_service、advance_service、import_service、lock_check、plan_service/rollback、calendar_service。
3. **能修则修**：只改 `backend/plugin/rider_salary/**`；若需改纲要，更新 `docs/设计/00-架构决策纲要.md` 的决策补遗；若需改框架，停止并写「⚠️ 需用户授权」。
4. **测试**：修完后 `pytest backend/plugin/rider_salary/tests -q` 全绿；新增/调整用例覆盖你发现的问题。
5. 更新 `docs/任务/待修复清单.md`：新增 ARCH 项或标「已修（ARCH-1）」。

## 交付
守则 §8，≤40 行：问题清单（严重度）、已修项、未修项与原因、测试数。
