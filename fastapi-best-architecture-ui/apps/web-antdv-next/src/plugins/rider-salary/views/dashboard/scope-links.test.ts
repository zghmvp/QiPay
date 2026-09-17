import { describe, expect, it } from 'vitest';

import {
  noPlanBindingTarget,
  noPlanViewAllTarget,
  pendingAdvanceRowTarget,
  pendingAdvancesViewAllTarget,
  periodStaleListParams,
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
