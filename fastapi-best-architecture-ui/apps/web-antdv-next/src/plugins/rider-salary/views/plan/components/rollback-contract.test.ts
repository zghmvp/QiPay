import { describe, expect, it } from 'vitest';

import {
  canSubmitRollback,
  rollbackNeedsConfirm,
  rollbackSuccessText,
} from './rollback-contract';

describe('回退弹窗契约', () => {
  it('纯草稿不要求确认文字，已发薪才要求', () => {
    expect(rollbackNeedsConfirm(false)).toBe(false);
    expect(rollbackNeedsConfirm(true)).toBe(true);
    expect(
      canSubmitRollback({
        confirmText: '',
        hasPaid: false,
        previewReady: true,
        reason: '方案配错',
      }),
    ).toBe(true);
    expect(
      canSubmitRollback({
        confirmText: '',
        hasPaid: true,
        previewReady: true,
        reason: '方案配错',
      }),
    ).toBe(false);
    expect(
      canSubmitRollback({
        confirmText: '确认回退',
        hasPaid: true,
        previewReady: true,
        reason: '方案配错',
      }),
    ).toBe(true);
  });

  it('成功文案带上版本号', () => {
    expect(rollbackSuccessText(4)).toBe(
      '回退完成，已复制草稿 v4，请修改后重新试算启用',
    );
  });
});
