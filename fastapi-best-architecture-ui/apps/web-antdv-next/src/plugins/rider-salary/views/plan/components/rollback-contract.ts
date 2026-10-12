export const ROLLBACK_CONFIRM_TEXT = '确认回退';

/** 只有预览标明已发薪时，才要求输入确认文字。 */
export function rollbackNeedsConfirm(hasPaid: boolean): boolean {
  return hasPaid;
}

export function canSubmitRollback(input: {
  confirmText: string;
  hasPaid: boolean;
  previewReady: boolean;
  reason: string;
}): boolean {
  if (!input.previewReady || !input.reason.trim()) return false;
  if (rollbackNeedsConfirm(input.hasPaid) && input.confirmText !== ROLLBACK_CONFIRM_TEXT) {
    return false;
  }
  return true;
}

/** 成功文案必须带上接口返回的版本号。 */
export function rollbackSuccessText(versionNo: number): string {
  return `回退完成，已复制草稿 v${versionNo}，请修改后重新试算启用`;
}
