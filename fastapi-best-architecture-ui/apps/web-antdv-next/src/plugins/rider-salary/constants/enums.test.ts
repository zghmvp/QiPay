import { describe, expect, it } from 'vitest';

import { AUDIT_MODULE_OPTIONS } from './enums';

describe('AUDIT_MODULE_OPTIONS', () => {
  it('筛选项包含预支，且文案与取值一致', () => {
    const advance = AUDIT_MODULE_OPTIONS.find((item) => item.value === '预支');
    expect(advance?.label).toBe('预支');
    const values = AUDIT_MODULE_OPTIONS.map((item) => item.value);
    expect(new Set(values).size).toBe(values.length);
    for (const item of AUDIT_MODULE_OPTIONS) {
      expect(item.label).toBe(item.value);
    }
  });
});
