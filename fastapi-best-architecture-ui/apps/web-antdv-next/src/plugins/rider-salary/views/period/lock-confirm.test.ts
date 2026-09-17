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

  it('优先用后端 confirm_hint', () => {
    const hint = buildLockConfirmHint({
      confirm_hint:
        '将冻结订单 120 笔、奖惩 4 笔、薪资单 18 张；将锁骑手 18 人；跳过骑手级覆盖 0 人',
      freeze_adjustment_count: 4,
      freeze_order_count: 120,
      freeze_payroll_count: 18,
      is_site_level: true,
      lock_rider_count: 18,
      skip_hint: '跳过骑手级覆盖 0 人',
      skip_rider_count: 0,
    });
    expect(hint).toContain('订单 120');
    expect(hint).toContain('奖惩 4');
    expect(hint).toContain('薪资单 18');
    expect(hint).toContain('将锁骑手 18 人');
    expect(hint).toContain('跳过骑手级覆盖 0 人');
  });

  it('缺 confirm_hint 时用冻结数与 skip_hint', () => {
    const hint = buildLockConfirmHint({
      confirm_hint: '',
      freeze_adjustment_count: 1,
      freeze_order_count: 9,
      freeze_payroll_count: 3,
      is_site_level: true,
      lock_rider_count: 3,
      skip_hint: '跳过骑手级覆盖 2 人',
      skip_rider_count: 2,
    });
    expect(hint).toContain('订单 9');
    expect(hint).toContain('将锁骑手 3 人');
    expect(hint).toContain('跳过骑手级覆盖 2 人');
    expect(hint).not.toContain('将锁骑手 5 人');
  });
});
