import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import {
  PERIOD_DELETE_PERM,
  canDeletePeriod,
  showPeriodDelete,
} from './delete-access';

const dataSource = readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), 'data.ts'),
  'utf8',
);

function removeOptionSource(source: string): string {
  const start = source.indexOf("code: 'remove'");
  const end = source.indexOf("text: '删除'", start);
  return source.slice(start, end);
}

describe('周期删除按钮权限', () => {
  it('只有删除权限且周期可删时显示', () => {
    const open = { payroll_count: 0, status: 'open' };
    expect(showPeriodDelete(true, open)).toBe(true);
    expect(showPeriodDelete(false, open)).toBe(false);
    expect(PERIOD_DELETE_PERM).toBe('rs:period:delete');
  });

  it('有薪资结果、非开放状态都不显示', () => {
    expect(canDeletePeriod({ payroll_count: 1, status: 'open' })).toBe(false);
    expect(showPeriodDelete(true, { payroll_count: 0, status: 'locked' })).toBe(
      false,
    );
    expect(
      showPeriodDelete(true, { payroll_count: 0, status: 'reopened' }),
    ).toBe(false);
    expect(showPeriodDelete(true, { status: 'open' })).toBe(true);
  });

  it('删除按钮判断 rs:period:delete，不再用生成权限', () => {
    const block = removeOptionSource(dataSource);
    expect(block).toContain('showPeriodDelete');
    expect(block).toContain(`'${PERIOD_DELETE_PERM}'`);
    expect(block).not.toContain('rs:period:generate');
  });
});
