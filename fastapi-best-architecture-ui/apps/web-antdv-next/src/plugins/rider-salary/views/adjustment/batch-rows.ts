export type BatchRowKind = 'complete' | 'empty' | 'incomplete';

export interface BatchDraftRow {
  amount?: number | string;
  biz_date?: string;
  remark?: string;
  rider_id?: number;
  subject_id?: number;
}

function hasText(value?: null | string): boolean {
  return Boolean(String(value ?? '').trim());
}

function hasAmount(value?: number | string): boolean {
  if (value === null || value === undefined || value === '') return false;
  return Number.isFinite(Number(value));
}

export function classifyBatchRow(row: BatchDraftRow): BatchRowKind {
  const filled = [
    Boolean(row.rider_id),
    hasText(row.biz_date),
    Boolean(row.subject_id),
    hasAmount(row.amount),
    hasText(row.remark),
  ].filter(Boolean).length;
  if (filled === 0) return 'empty';
  if (row.rider_id && hasText(row.biz_date) && row.subject_id && hasAmount(row.amount)) {
    return 'complete';
  }
  return 'incomplete';
}

export function batchSubmitMessage(entered: number, skipped: number): string {
  return `已录入 ${entered} 行，跳过未完整 ${skipped} 行`;
}

export function isBatchAllSuccessCopy(text: string): boolean {
  return text.includes('批量录入成功');
}
