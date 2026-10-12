import { describe, expect, it } from 'vitest';

import {
  batchOpenAccountHint,
  batchResetPasswordHint,
  openAccountHint,
  resetPasswordHint,
  specifiedPasswordMessage,
} from './password-hint';

describe('开户和重置密码提示', () => {
  it('不再提示手机号后 6 位', () => {
    const texts = [
      openAccountHint('D5A099'),
      resetPasswordHint(),
      specifiedPasswordMessage('开通账号'),
    ];
    for (const text of texts) {
      expect(text).not.toContain('手机号后');
      expect(text).toContain('首次登录必须修改');
    }
    expect(openAccountHint('D5A099')).toContain('仅展示一次');
    expect(resetPasswordHint()).toContain('仅展示一次');
  });

  it('批量开户和重置不使用统一口令', () => {
    for (const text of [batchOpenAccountHint(3), batchResetPasswordHint(3)]) {
      expect(text).toContain('随机密码');
      expect(text).toContain('仅展示一次');
      expect(text).toContain('首次登录必须修改');
      expect(text).toContain('不会使用统一口令');
    }
  });
});