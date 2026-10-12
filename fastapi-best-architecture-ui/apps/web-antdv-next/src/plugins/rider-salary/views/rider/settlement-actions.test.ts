import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { settlementActions } from './settlement-actions';

const HERE = dirname(fileURLToPath(import.meta.url));

describe('离职结算向导按钮', () => {
  it('开放和补发中可以算薪、锁账', () => {
    expect(settlementActions('open')).toEqual({
      calculate: true,
      lock: true,
      markPaid: false,
      paid: false,
    });
    expect(settlementActions('reopened').lock).toBe(true);
  });

  it('锁账后只能标记发薪，发薪后不再出现写按钮', () => {
    expect(settlementActions('locked')).toEqual({
      calculate: false,
      lock: false,
      markPaid: true,
      paid: false,
    });
    expect(settlementActions('paid').paid).toBe(true);
    expect(settlementActions('paid').markPaid).toBe(false);
  });

  it('锁账和标记发薪带上当前状态', () => {
    const source = readFileSync(
      resolve(HERE, 'components/LeaveSettlementPanel.vue'),
      'utf8',
    );
    expect(source).toContain(
      'lockPeriodWithExpectedStatusApi(id, reason.value.trim(), status.value)',
    );
    expect(source).toContain('markPaidPeriodWithExpectedStatusApi');
    expect(source).toContain('status.value');
  });
});
