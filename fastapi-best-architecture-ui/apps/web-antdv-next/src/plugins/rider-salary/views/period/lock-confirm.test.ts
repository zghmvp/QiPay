import { describe, expect, it } from 'vitest';

import {
  buildLockConfirmHint,
  isSiteLevelPeriod,
} from './lock-confirm';

describe('site-level lock confirm', () => {
  it('rider_id=0 是站点级', () => {
    expect(isSiteLevelPeriod({ rider_id: 0 })).toBe(true);
    expect(isSiteLevelPeriod({ rider_id: 12 })).toBe(false);
  });

  it('写出将冻结四数与跳过人数，M 为 0 也出现', () => {
    const hint = buildLockConfirmHint({
      adjustment_count: 4,
      lock_rider_count: 18,
      order_count: 120,
      payroll_count: 18,
      skipped_rider_level_count: 0,
    });
    expect(hint).toContain('订单 120');
    expect(hint).toContain('奖惩 4');
    expect(hint).toContain('薪资单 18');
    expect(hint).toContain('将锁骑手 18 人');
    expect(hint).toContain('跳过骑手级覆盖 0 人');
    expect(hint).not.toMatch(/本周期|本期工资条/);
  });

  it('不把窗内 rider_count 当成将锁人数', () => {
    const hint = buildLockConfirmHint({
      lock_rider_count: 3,
      skipped_rider_count: 2,
      will_lock_adjustment_count: 1,
      will_lock_order_count: 9,
      will_lock_payroll_count: 3,
    });
    expect(hint).toContain('将锁骑手 3 人');
    expect(hint).toContain('跳过骑手级覆盖 2 人');
    expect(hint).not.toContain('将锁骑手 5 人');
  });
});
