import { describe, expect, it } from 'vitest';

import {
  ORDER_WRITE_STALE_HINT,
  monthFromBizDate,
  orderWriteSuccessMessage,
  resolveOrderWriteLanding,
} from './stale-after-write';

describe('order write stale landing', () => {
  it('成功文案必须写出需重算 / 未出账，不得只写已纠错', () => {
    expect(orderWriteSuccessMessage('fix')).toContain('已纠错订单');
    expect(orderWriteSuccessMessage('fix')).toContain('需重算');
    expect(orderWriteSuccessMessage('fix')).toContain('尚未出账');
    expect(orderWriteSuccessMessage('backfill')).toContain('已补录订单');
    expect(orderWriteSuccessMessage('backfill')).toContain(ORDER_WRITE_STALE_HINT);
    expect(orderWriteSuccessMessage('fix')).not.toBe('已纠错订单');
    expect(orderWriteSuccessMessage('backfill')).not.toBe('已补录订单');
  });

  it('覆盖 open 期落到该 period_id 算薪页', () => {
    const landing = resolveOrderWriteLanding({
      bizDate: '2026-09-12',
      periodId: 42,
      periodStatus: 'open',
      siteId: 3,
    });
    expect(landing.path).toBe('/rider-salary/period/42/calculate');
    expect(landing.ctaLabel).toBe('去该期算薪');
    expect(landing.path).not.toMatch(/\/period$/);
  });

  it('reopened 也进该期算薪页', () => {
    const landing = resolveOrderWriteLanding({
      bizDate: '2026-09-12',
      periodId: 9,
      periodStatus: 'reopened',
      siteId: 3,
    });
    expect(landing.path).toBe('/rider-salary/period/9/calculate');
  });

  it('无覆盖期落到该站周期列表带月，不假装已出账', () => {
    const landing = resolveOrderWriteLanding({
      bizDate: '2026-09-12',
      periodId: null,
      siteId: 3,
    });
    expect(landing.path).toBe('/rider-salary/period');
    expect(landing.query.site_id).toBe('3');
    expect(landing.query.month).toBe('2026-09');
    expect(landing.ctaLabel).toBe('去周期列表');
    expect(monthFromBizDate('2026-09-12T08:00:00')).toBe('2026-09');
  });

  it('locked 覆盖期不得当算薪页，回该站周期列表', () => {
    const landing = resolveOrderWriteLanding({
      bizDate: '2026-09-12',
      periodId: 42,
      periodStatus: 'locked',
      siteId: 3,
    });
    expect(landing.path).toBe('/rider-salary/period');
    expect(landing.query.month).toBe('2026-09');
    expect(landing.path).not.toContain('/calculate');
  });
});
