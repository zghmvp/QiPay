import { describe, expect, it } from 'vitest';

import {
  importOutcomeDetail,
  importOutcomeHeadline,
  isImportAllSuccess,
} from './import-outcome';

describe('import skip-errors outcome copy', () => {
  it('failed_rows>0 不写全部导入成功', () => {
    const half = { failed_rows: 1, success_rows: 3 };
    expect(isImportAllSuccess(half)).toBe(false);
    expect(importOutcomeHeadline(half)).toContain('失败 1 行');
    expect(importOutcomeHeadline(half)).toContain('成功 3 行');
    expect(importOutcomeHeadline(half)).not.toContain('全部导入成功');
    expect(importOutcomeDetail(half)).toBe('成功 3 行，失败 1 行');
  });

  it('零失败才允许全部导入成功', () => {
    const ok = { failed_rows: 0, success_rows: 4 };
    expect(isImportAllSuccess(ok)).toBe(true);
    expect(importOutcomeHeadline(ok)).toBe('全部导入成功');
  });
});
