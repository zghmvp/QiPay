# UX-1｜管理后台表格高度与页面排版修复

## 必读
- `docs/设计/02-开发子角色通用守则.md`
- `docs/任务/前端-F0-通用约定.md`
- `docs/research/前端架构调研.md` §5
- 对照：`src/plugins/notice/views/index.vue`（`<Page auto-content-height>` 直接包 `<Grid>`）
- 问题页：`src/plugins/rider-salary/views/**` 全部列表页 + 方案/plan 列表

## 用户反馈
每个页面的表格高度异常，会自动缩小高度。

## 排查方向（按优先级）
1. **`PageContainer.vue`**：当前 `<Page auto-content-height><div class="p-1"><slot/></div></Page>` 中间层可能打断 flex 高度链。对照 notice/system 页，修成与 FBA 一致（如 `h-full min-h-0 flex flex-col` 或去掉中间层，直接在页面用 `<Page auto-content-height>`）。
2. **所有 `useVbenVxeGrid` 列表页**（site/rider/subject/adjustment/day-flag/notice/audit/order/period/advance/plan 等）：确认 `gridOptions.height: 'auto'` 与 Page 组合正确；禁止写死过小 height；检查是否有 CSS 覆盖 `.vxe-table--body-wrapper`。
3. **非列表页**：calendar/dashboard/plan/editor 是否有 overflow/高度问题一并修。
4. **性能导致的「闪缩」**：如 `site/index.vue` 在 proxy query 里对每个站点再请求 managers（N+1），可能导致表格多次 reflow——改为列 lazy 加载或后端 list 带 manager_count，避免整表高度抖动（若后端无字段，至少不要在 query 回调里 await 改 row 再 return，改用单独列渲染时 fetch 或去掉 manager_count 列的同步填充）。

## 约束
- 只改 `src/plugins/rider-salary/**`
- 不改框架、不新增 npm 依赖
- 验收：`pnpm -F @vben/web-antdv-next typecheck` + eslint 0 error；用 Playwright（`scripts/t2_acceptance.mjs` 可扩展或新建 `scripts/ux_check.mjs`）对至少 **站点列表、订单列表、结算周期、日历、工作台** 截图，表格应占满内容区、分页在底部、窗口 resize 后高度稳定
- 更新 `docs/任务/待修复清单.md` 追加 #18 并标状态

## 交付
守则 §8，≤35 行：根因、改了哪些文件、截图路径、剩余风险。
