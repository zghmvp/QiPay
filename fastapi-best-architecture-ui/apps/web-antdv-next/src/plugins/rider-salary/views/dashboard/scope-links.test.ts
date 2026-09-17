import { describe, expect, it } from 'vitest';

import {
  abnormalAttentionTarget,
  abnormalOrderRowTarget,
  importGapWizardPreset,
  noPlanBindingTarget,
  noPlanViewAllTarget,
  orderImportTarget,
  pendingAdvanceRowTarget,
  pendingAdvancesViewAllTarget,
  periodStaleListParams,
  resignedWithOrdersRowTarget,
  resignedWithOrdersViewAllTarget,
  stalePeriodCalcTarget,
  stalePeriodsViewAllTarget,
} from './scope-links';

describe('no-plan dashboard targets', () => {
  it('该行走档案绑定时间轴，不是日历', () => {
    const target = noPlanBindingTarget(88, 3, '2026-09');
    expect(target.path).toBe('/rider-salary/rider/88');
    expect(target.query.tab).toBe('binding');
    expect(target.path).not.toContain('calendar');
  });

  it('查看全部走骑手名单 from=no_plan，不是空日历', () => {
    const target = noPlanViewAllTarget(3, '2026-09');
    expect(target.path).toBe('/rider-salary/rider');
    expect(target.query.from).toBe('no_plan');
    expect(target.query.site_id).toBe('3');
    expect(target.path).not.toContain('calendar');
  });
});

describe('stale dashboard targets', () => {
  it('查看全部带 stale=1 与当前站+月', () => {
    const target = stalePeriodsViewAllTarget(3, '2026-09');
    expect(target.path).toBe('/rider-salary/period');
    expect(target.query.stale).toBe('1');
    expect(target.query.site_id).toBe('3');
    expect(target.query.month).toBe('2026-09');
  });

  it('无站仍带月份', () => {
    const target = stalePeriodsViewAllTarget(undefined, '2026-09');
    expect(target.query.stale).toBe('1');
    expect(target.query.month).toBe('2026-09');
    expect(target.query.site_id).toBeUndefined();
  });

  it('该行走算薪页，不是周期抽屉，也不自动开算', () => {
    const target = stalePeriodCalcTarget(42);
    expect(target.path).toBe('/rider-salary/period/42/calculate');
    expect(target.query.id).toBeUndefined();
    expect(target.query.auto).toBeUndefined();
    expect(target.path).not.toMatch(/\/period$/);
  });
});

describe('pending advance dashboard targets', () => {
  it('查看全部带 pending + 当前站月', () => {
    const target = pendingAdvancesViewAllTarget(3, '2026-09');
    expect(target.path).toBe('/rider-salary/advance');
    expect(target.query.status).toBe('pending');
    expect(target.query.site_id).toBe('3');
    expect(target.query.month).toBe('2026-09');
  });

  it('无站仍带月份', () => {
    const target = pendingAdvancesViewAllTarget(undefined, '2026-09');
    expect(target.query.status).toBe('pending');
    expect(target.query.month).toBe('2026-09');
    expect(target.query.site_id).toBeUndefined();
  });

  it('该行带 id，能办这一条', () => {
    const target = pendingAdvanceRowTarget(77, 3, '2026-09');
    expect(target.path).toBe('/rider-salary/advance');
    expect(target.query.id).toBe('77');
    expect(target.query.status).toBe('pending');
    expect(target.query.site_id).toBe('3');
    expect(target.query.month).toBe('2026-09');
  });
});

describe('import gap wizard preset', () => {
  it('预填该行站+单日窗，不是订单空列表', () => {
    const preset = importGapWizardPreset(
      { date: '2026-09-12', site_id: 3 },
      undefined,
    );
    expect(preset).toEqual({
      date: '2026-09-12',
      date_from: '2026-09-12',
      date_to: '2026-09-12',
      site_id: 3,
    });
  });

  it('已选站时不得串到别站', () => {
    const preset = importGapWizardPreset(
      { date: '2026-09-12', site_id: 9 },
      3,
    );
    expect(preset?.site_id).toBe(3);
    expect(preset?.date).toBe('2026-09-12');
  });

  it('查看全部仍走带窗订单，不代替向导', () => {
    const viewAll = orderImportTarget(3, '2026-09');
    expect(viewAll.path).toBe('/rider-salary/order');
    expect(viewAll.query.site_id).toBe('3');
    expect(viewAll.query.date_from).toBeTruthy();
    expect(viewAll.query.import).toBeUndefined();
  });
});

describe('abnormal order row target', () => {
  it('该行带 id，查看全部不带 id、仍 attention=1', () => {
    const row = abnormalOrderRowTarget(55, 3, '2026-09', 'AB-1');
    expect(row.path).toBe('/rider-salary/order');
    expect(row.query.id).toBe('55');
    expect(row.query.order_no).toBe('AB-1');
    expect(row.query.attention).toBe('1');
    expect(row.query.status).toBeUndefined();
    const viewAll = abnormalAttentionTarget(3, '2026-09');
    expect(viewAll.query.attention).toBe('1');
    expect(viewAll.query.id).toBeUndefined();
    expect(viewAll.query.site_id).toBe('3');
  });
});

describe('resigned with orders targets', () => {
  it('该行走该骑手档案并带本月，不是离职总名单', () => {
    const row = resignedWithOrdersRowTarget(88, 3, '2026-09');
    expect(row.path).toBe('/rider-salary/rider/88');
    expect(row.query.month).toBe('2026-09');
    expect(row.query.site_id).toBe('3');
    expect(row.path).not.toBe('/rider-salary/rider');
    expect(row.query.status).toBeUndefined();
    expect(row.query.rider_id).toBeUndefined();
  });

  it('查看全部吃 status=resigned，已选站带站月', () => {
    const viewAll = resignedWithOrdersViewAllTarget(3, '2026-09');
    expect(viewAll.path).toBe('/rider-salary/rider');
    expect(viewAll.query.status).toBe('resigned');
    expect(viewAll.query.site_id).toBe('3');
    expect(viewAll.query.month).toBe('2026-09');
  });

  it('未选站查看全部仍吃 resigned，不带站', () => {
    const viewAll = resignedWithOrdersViewAllTarget(undefined, '2026-09');
    expect(viewAll.query.status).toBe('resigned');
    expect(viewAll.query.site_id).toBeUndefined();
    expect(viewAll.query.month).toBeUndefined();
  });
});

describe('stale list params', () => {
  it('周期列表请求带 stale 与站月', () => {
    const scoped = periodStaleListParams(3, '2026-09');
    expect(scoped.stale).toBe(true);
    expect(scoped.site_id).toBe(3);
    expect(scoped.month).toBe('2026-09');
    const monthOnly = periodStaleListParams(undefined, '2026-09');
    expect(monthOnly.stale).toBe(true);
    expect(monthOnly.month).toBe('2026-09');
    expect(monthOnly.site_id).toBeUndefined();
  });
});
