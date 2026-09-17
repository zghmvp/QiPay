import { describe, expect, it } from 'vitest';

import { formatAdvanceQuota, resolveAdvanceQuota } from './helpers';

describe('resolveAdvanceQuota', () => {
  it('读取嵌套 quota', () => {
    expect(
      resolveAdvanceQuota({
        quota: { limit: 1, remaining: 0, used: 1 },
      } as never),
    ).toEqual({ limit: 1, remaining: 0, used: 1 });
  });

  it('读取扁平 monthly_advance_* 字段', () => {
    expect(
      resolveAdvanceQuota({
        monthly_advance_limit: 2,
        monthly_advance_remaining: 1,
        monthly_advance_used: 1,
      } as never),
    ).toEqual({ limit: 2, remaining: 1, used: 1 });
  });

  it('没有次数字段时返回空，不把 remaining_amount 当成次数', () => {
    expect(
      resolveAdvanceQuota({
        amount: '100',
        remaining_amount: '50',
      } as never),
    ).toBeNull();
  });
});

describe('formatAdvanceQuota', () => {
  it('limit=0 用禁止预支文案，不用金额文案', () => {
    expect(formatAdvanceQuota({ limit: 0, remaining: 0, used: 0 })).toBe(
      '本站暂不可预支',
    );
  });

  it('展示已用 / 上限 / 剩余', () => {
    expect(formatAdvanceQuota({ limit: 2, remaining: 1, used: 1 })).toBe(
      '已用 1 / 2（剩 1）',
    );
  });
});
