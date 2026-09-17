import { describe, expect, it } from 'vitest';

import {
  formulaAddsManualField,
  formulaFieldLabel,
  MANUAL_NOT_DOUBLE_COPY,
  manualFieldUsedAsAddend,
} from './helpers';

describe('manual period fields', () => {
  it('拼装器文案硬区分可作条件 ≠ 加进公式', () => {
    expect(MANUAL_NOT_DOUBLE_COPY).toContain('可作条件');
    expect(MANUAL_NOT_DOUBLE_COPY).toContain('加进公式 = 双计');
    expect(MANUAL_NOT_DOUBLE_COPY).toContain('手工明细已入账');
    expect(MANUAL_NOT_DOUBLE_COPY).toContain('再加会双计');
    expect(formulaFieldLabel('本期手工奖')).toBe('本期手工奖（可作条件；加进公式=双计）');
  });

  it('保底相减不是加项，单独字段或求和是加项', () => {
    expect(manualFieldUsedAsAddend('最大值(0, 3500 − 本期已计金额 − 本期手工奖)')).toBe(false);
    expect(manualFieldUsedAsAddend('本期手工奖')).toBe(true);
    expect(manualFieldUsedAsAddend('本期手工奖 + 100')).toBe(true);
    expect(manualFieldUsedAsAddend('100 + 本期手工惩')).toBe(true);
  });

  it('字段乘单价选手工奖算加项', () => {
    expect(
      formulaAddsManualField({ 类型: '字段乘单价', 字段: '本期手工奖', 单价: 1, 起算值: 0 }),
    ).toBe(true);
    expect(formulaAddsManualField({ 类型: '固定金额', 金额: 200 })).toBe(false);
  });
});
