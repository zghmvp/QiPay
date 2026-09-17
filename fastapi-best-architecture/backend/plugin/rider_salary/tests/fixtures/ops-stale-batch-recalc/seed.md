# 本站本月 stale 批量重算 · 演示灌种

## 必须满足

1. 账号 `site_owner_d2` / `Rider@123456`（`is_staff=true`，角色「站点负责人」`92002`）
2. `rs_site_manager` 覆盖福民 `SZ0050`（优先 `owner`；站已有 owner 则用 `deputy`）
3. 福民开放月 ≥2 名骑手 payroll `stale=true`（走奖惩 `mark_stale`，不 wipe 灯塔订单）
4. **正式 CDP 不得**用 `CDP_SITE_OWNER=admin` 冒充 Must #5
5. 夹具含 FIX_C17_R1 无方案有单时，**确认后**不得纯绿「完成」；须见 `dashboard-batch-failed` / 部分失败，并能 `dashboard-batch-goto-calc` 看到该骑手
6. **禁止** `CDP_ALLOW_EMPTY_STALE=1` 换绿

## 灌种

```bash
API_URL=http://127.0.0.1:8000 CDP_USER=admin CDP_PASS=admin \
  node scripts/cdp/seed-xiaoxiang-fixtures.mjs
```

复跑：

```bash
CDP_URL=http://127.0.0.1:9222 CDP_SITE_ID=<福民> CDP_MONTH=2026-09 \
  node scripts/cdp/harness.mjs ops-stale-batch-recalc
# 默认 CDP_SITE_OWNER=site_owner_d2 / CDP_SITE_OWNER_PASS=Rider@123456
# 逃生阀（仅排障）：CDP_ALLOW_EMPTY_STALE=1
```

场景名：`ops-stale-batch-recalc`
