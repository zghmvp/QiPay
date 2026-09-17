import { describe, expect, it } from 'vitest';

import { riderPeriodPayslipQuery } from './payslip';

describe('rider period payslip target', () => {
  it('带 rider_id + period_id，不进周期抽屉', () => {
    const target = riderPeriodPayslipQuery(88, 12);
    expect(target).toEqual({
      path: '/rider-salary/payroll',
      query: { period_id: '12', rider_id: '88' },
    });
    expect(JSON.stringify(target)).not.toContain('/period');
  });
});
