export interface ImportOutcomeCounts {
  failed_rows: number;
  success_rows: number;
}

export function isImportAllSuccess(result: ImportOutcomeCounts): boolean {
  return Number(result.failed_rows ?? 0) <= 0;
}

/** 半成功不得读成全部入库。 */
export function importOutcomeHeadline(result: ImportOutcomeCounts): string {
  const success = Number(result.success_rows ?? 0);
  const failed = Number(result.failed_rows ?? 0);
  if (failed > 0) {
    return `成功 ${success} 行，失败 ${failed} 行未入库`;
  }
  return '全部导入成功';
}

export function importOutcomeDetail(result: ImportOutcomeCounts): string {
  const success = Number(result.success_rows ?? 0);
  const failed = Number(result.failed_rows ?? 0);
  return `成功 ${success} 行，失败 ${failed} 行`;
}
