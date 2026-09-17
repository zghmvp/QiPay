import { describe, expect, it } from 'vitest';

import type { PayrollDailyResult, PayrollDetailItem } from '../../types/payroll';

import { isEmptyPayrollDay, partitionPayrollDailies } from './helpers';

function day(
  partial: Partial<PayrollDailyResult> & Pick<PayrollDailyResult, 'biz_date'>,
): PayrollDailyResult {
  return {
    day_status: 'no_orders',
    formula_amount: '0',
    manual_bonus: '0',
    manual_penalty: '0',
    net_adjust: '0',
    order_count: 0,
    rider_id: 1,
    valid_order_count: 0,
    ...partial,
  };
}

describe('isEmptyPayrollDay', () => {
  it('默认藏未导入、零单无金额', () => {
    expect(isEmptyPayrollDay(day({ biz_date: '2026-09-01', day_status: 'not_imported' }))).toBe(
      true,
    );
    expect(isEmptyPayrollDay(day({ biz_date: '2026-09-02', day_status: 'no_orders' }))).toBe(true);
  });

  it('有奖 / 有惩 / 有预支默认可见', () => {
    expect(
      isEmptyPayrollDay(
        day({ biz_date: '2026-09-03', day_status: 'not_imported', manual_bonus: '10' }),
      ),
    ).toBe(false);
    expect(
      isEmptyPayrollDay(
        day({ biz_date: '2026-09-04', day_status: 'no_orders', manual_penalty: '-5' }),
      ),
    ).toBe(false);
    const advance: PayrollDetailItem = {
      amount: '80',
      biz_date: '2026-09-05',
      include_in_gross: false,
      rider_id: 1,
      source: 'advance',
      stage: 'period',
      subject_id: 1,
    };
    expect(
      isEmptyPayrollDay(day({ biz_date: '2026-09-05', day_status: 'no_orders' }), [advance]),
    ).toBe(false);
  });

  it('no_plan 且有完成单是真缺口，默认可见', () => {
    expect(
      isEmptyPayrollDay(
        day({
          biz_date: '2026-09-06',
          day_status: 'no_plan',
          order_count: 2,
          valid_order_count: 2,
        }),
      ),
    ).toBe(false);
  });

  it('no_plan 零单仍算空日', () => {
    expect(isEmptyPayrollDay(day({ biz_date: '2026-09-07', day_status: 'no_plan' }))).toBe(true);
  });

  it('有单或有公式金额默认可见', () => {
    expect(
      isEmptyPayrollDay(day({ biz_date: '2026-09-08', day_status: 'has_data', order_count: 1 })),
    ).toBe(false);
    expect(
      isEmptyPayrollDay(
        day({ biz_date: '2026-09-09', day_status: 'no_orders', formula_amount: '12.5' }),
      ),
    ).toBe(false);
  });

  it('partition 不丢空日，只分可见/空', () => {
    const days = [
      day({ biz_date: '2026-09-01', day_status: 'not_imported' }),
      day({ biz_date: '2026-09-02', day_status: 'has_data', order_count: 3 }),
    ];
    const { empty, visible } = partitionPayrollDailies(days);
    expect(empty).toHaveLength(1);
    expect(visible).toHaveLength(1);
    expect(empty[0]?.biz_date).toBe('2026-09-01');
  });
});
