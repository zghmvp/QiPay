import { describe, expect, it } from 'vitest';

import {
  formatMonthlyAdvanceLimit,
  normalizeMonthlyAdvanceLimit,
} from './helpers';

describe('normalizeMonthlyAdvanceLimit', () => {
  it('空值按 1 保存', () => {
    expect(normalizeMonthlyAdvanceLimit(undefined)).toBe(1);
    expect(normalizeMonthlyAdvanceLimit(null)).toBe(1);
    expect(normalizeMonthlyAdvanceLimit('')).toBe(1);
    expect(normalizeMonthlyAdvanceLimit('  ')).toBe(1);
  });

  it('0 表示本站禁止预支，不得改成 1', () => {
    expect(normalizeMonthlyAdvanceLimit(0)).toBe(0);
    expect(normalizeMonthlyAdvanceLimit('0')).toBe(0);
  });

  it('截断小数并拒绝负数', () => {
    expect(normalizeMonthlyAdvanceLimit(2.9)).toBe(2);
    expect(normalizeMonthlyAdvanceLimit(-3)).toBe(0);
  });
});

describe('formatMonthlyAdvanceLimit', () => {
  it('未返回时显示破折号，不假装已是 1', () => {
    expect(formatMonthlyAdvanceLimit(undefined)).toBe('—');
    expect(formatMonthlyAdvanceLimit(null)).toBe('—');
  });

  it('0 标明禁止预支，不写成金额文案', () => {
    expect(formatMonthlyAdvanceLimit(0)).toBe('0（本站禁止预支）');
    expect(formatMonthlyAdvanceLimit(2)).toBe('2');
  });
});
