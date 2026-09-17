import { describe, expect, it } from 'vitest';

import {
  applyRiderNames,
  isSiteLevelPeriodRow,
  periodRowLevelLabel,
} from './period-row-level';

describe('period row level label', () => {
  it('rider_id=0 标站点级，不写骑手名', () => {
    const row = {
      period_id: 11,
      range: '2026-09-01 ~ 2026-09-15',
      rider_id: 0,
      rider_name: '张三',
    };
    expect(isSiteLevelPeriodRow(row)).toBe(true);
    expect(periodRowLevelLabel(row)).toBe('站点级');
    expect(periodRowLevelLabel(row)).not.toContain('张三');
  });

  it('缺 rider_id 也当站点级', () => {
    const row = { period_id: 12, range: '2026-09-01 ~ 2026-09-15' };
    expect(periodRowLevelLabel(row)).toBe('站点级');
  });

  it('骑手级写工号+姓名', () => {
    const row = {
      job_no: 'D5A001',
      period_id: 13,
      range: '2026-09-01 ~ 2026-09-15',
      rider_id: 88,
      rider_name: '李四',
    };
    expect(isSiteLevelPeriodRow(row)).toBe(false);
    expect(periodRowLevelLabel(row)).toBe('D5A001 李四');
  });

  it('同 range 两行能分清站点级 vs 骑手', () => {
    const range = '2026-09-01 ~ 2026-09-15';
    const site = periodRowLevelLabel({ period_id: 1, range, rider_id: 0 });
    const rider = periodRowLevelLabel({
      name: '王五',
      period_id: 2,
      range,
      rider_id: 9,
    });
    expect(site).toBe('站点级');
    expect(rider).toBe('王五');
    expect(site).not.toBe(rider);
  });

  it('补姓名不覆盖站点级、不覆盖已有姓名', () => {
    const names = new Map([[7, { job_no: 'A01', name: '赵六' }]]);
    const filled = applyRiderNames(
      [
        { period_id: 1, rider_id: 0 },
        { period_id: 2, rider_id: 7 },
        { period_id: 3, rider_id: 8, rider_name: '已有' },
      ],
      names,
    );
    expect(periodRowLevelLabel(filled[0]!)).toBe('站点级');
    expect(periodRowLevelLabel(filled[1]!)).toBe('A01 赵六');
    expect(filled[2]!.rider_name).toBe('已有');
  });
});
