import { describe, expect, it } from 'vitest';

import {
  batchAccountBody,
  batchBindingBody,
  batchRiderSummary,
  formatIssuedPasswords,
  selectedRiderIds,
} from './batch-ops';

describe('批量运营', () => {
  it('勾选去重并丢掉空 ID', () => {
    expect(
      selectedRiderIds([{ id: 1 }, { id: 1 }, { id: null }, {}, { id: 4 }]),
    ).toEqual([1, 4]);
  });

  it('绑定和账号请求都不带统一密码', () => {
    const binding = batchBindingBody([2, 3], {
      binding_type: 'default',
      end_date: '',
      plan_version_id: 9,
      remark: '  ',
      start_date: '2026-10-01',
    });
    expect(binding).toEqual({
      binding_type: 'default',
      end_date: null,
      plan_version_id: 9,
      remark: null,
      rider_ids: [2, 3],
      start_date: '2026-10-01',
    });
    expect(binding).not.toHaveProperty('password');

    const account = batchAccountBody([2, 3], ' 批量开户 ');
    expect(account).toEqual({ reason: '批量开户', rider_ids: [2, 3] });
    expect(account).not.toHaveProperty('password');
    expect(Object.keys(batchAccountBody([1]))).toEqual(['reason', 'rider_ids']);
  });

  it('摘要和密码清单按人数展开', () => {
    const riders = Array.from({ length: 10 }, (_, index) => ({
      job_no: `D${index + 1}`,
      name: `骑手${index + 1}`,
    }));
    expect(batchRiderSummary(riders, 2)).toBe('D1 骑手1、D2 骑手2 等 10 人');
    const text = formatIssuedPasswords([
      { initial_password: 'aA1!xxxxxx', name: '甲', username: 'D0001' },
      { initial_password: 'bB2!yyyyyy', name: '乙', username: 'D0002' },
    ]);
    expect(text).toContain('工号\t姓名\t初始密码');
    expect(text).toContain('D0001\t甲\taA1!xxxxxx');
    expect(text).toContain('D0002\t乙\tbB2!yyyyyy');
  });
});
