# 日历无方案深链 · 演示灌种

与 Must #2 共用骑手 **`FIX_C17_R1`**（契约见 `../trial-binding-segments/seed.json`）。

## 必须满足

- 站点：福民 `SZ0050`
- 绑定：`9/1–9/14` 有方案；**`9/15–9/17` 无方案**；`9/18–9/30` 有方案
- 无方案三日各有 ≥1 笔 `completed` 订单（订单号前缀 `FIX_C17_`）
- **禁止**为过测在非 `no_plan` 日强显「去绑方案」

## 灌种

```bash
# 演示机（后端 :8000 已起；默认 admin/admin）
API_URL=http://127.0.0.1:8000 CDP_USER=admin CDP_PASS=admin \
  node scripts/cdp/seed-xiaoxiang-fixtures.mjs
```

脚本幂等；成功后打印 `CDP_SITE_ID` / `CDP_RIDER_ID`，再跑：

```bash
CDP_URL=http://127.0.0.1:9222 CDP_PASS=admin \
  CDP_SITE_ID=<福民> CDP_RIDER_ID=<FIX_C17_R1_id> CDP_MONTH=2026-09 \
  node scripts/cdp/harness.mjs ops-calendar-no-plan-deeplink
```

场景名：`ops-calendar-no-plan-deeplink`
