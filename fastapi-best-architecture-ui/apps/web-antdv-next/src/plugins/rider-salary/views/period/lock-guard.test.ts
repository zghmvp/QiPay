import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { canConfirmPeriodLock, supplementRiderIds } from './lock-guard';

const here = dirname(fileURLToPath(import.meta.url));
const modalSource = readFileSync(
  resolve(here, 'components/LockModal.vue'),
  'utf8',
);
const apiSource = readFileSync(resolve(here, '../../api/period.ts'), 'utf8');

const uncalculated = [
  { job_no: 'R0051', rider_id: 51, rider_name: '骑手51' },
  { job_no: 'R0008', rider_id: 8, rider_name: '骑手8' },
];
const needsRecalc = [{ job_no: 'R0012', rider_id: 12, rider_name: '骑手12' }];

describe('锁账预检名单与按钮', () => {
  it('有未算薪骑手时锁账按钮置灰，并保留名单顺序', () => {
    expect(
      canConfirmPeriodLock({
        canLock: true,
        uncalculatedCount: uncalculated.length,
      }),
    ).toBe(false);
    expect(
      canConfirmPeriodLock({
        canLock: false,
        uncalculatedCount: uncalculated.length,
      }),
    ).toBe(false);
    expect(
      supplementRiderIds({
        needs_recalc: needsRecalc,
        uncalculated,
      }),
    ).toEqual([51, 8, 12]);
  });

  it('需重算时同样不能锁；没有差异且预检允许时可以锁', () => {
    expect(
      canConfirmPeriodLock({
        canLock: true,
        needsRecalcCount: 1,
        uncalculatedCount: 0,
      }),
    ).toBe(false);
    expect(
      canConfirmPeriodLock({
        canLock: true,
        needsRecalcCount: 0,
        uncalculatedCount: 0,
      }),
    ).toBe(true);
    expect(
      canConfirmPeriodLock({
        canLock: false,
        uncalculatedCount: 0,
      }),
    ).toBe(false);
    expect(
      canConfirmPeriodLock({
        canLock: true,
        loading: true,
        uncalculatedCount: 0,
      }),
    ).toBe(false);
    expect(supplementRiderIds(null)).toEqual([]);
  });

  it('弹窗调用预检并列出两类骑手，锁账请求不改 expected_status', () => {
    expect(modalSource).toContain('lockCheckPeriodApi');
    expect(modalSource).toContain('canConfirmPeriodLock');
    expect(modalSource).toContain('未算薪');
    expect(modalSource).toContain('需重算');
    expect(modalSource).toContain(
      'lockPeriodApi(period.id, reason.value.trim())',
    );
    expect(modalSource).not.toContain('expected_status');

    const lockFn = apiSource.slice(
      apiSource.indexOf('export async function lockPeriodApi'),
      apiSource.indexOf('export async function markPaidPeriodApi'),
    );
    expect(lockFn).toContain('{ reason }');
    expect(lockFn).not.toContain('expected_status');
  });
});
