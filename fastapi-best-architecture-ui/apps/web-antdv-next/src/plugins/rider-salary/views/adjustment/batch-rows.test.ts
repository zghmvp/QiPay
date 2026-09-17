import { describe, expect, it } from 'vitest';

import {
  batchSubmitMessage,
  classifyBatchRow,
  isBatchAllSuccessCopy,
} from './batch-rows';

describe('batch adjustment incomplete rows', () => {
  it('空白新增行不计，半填行算跳过，完整行入库', () => {
    expect(classifyBatchRow({ remark: '' })).toBe('empty');
    expect(
      classifyBatchRow({
        biz_date: '2026-09-12',
        rider_id: 8,
      }),
    ).toBe('incomplete');
    expect(
      classifyBatchRow({
        amount: 12,
        biz_date: '2026-09-12',
        rider_id: 8,
        subject_id: 3,
      }),
    ).toBe('complete');
  });

  it('半填时主文案同时给 N/M，不得只写批量录入成功', () => {
    const text = batchSubmitMessage(2, 1);
    expect(text).toContain('已录入 2');
    expect(text).toContain('跳过未完整 1');
    expect(isBatchAllSuccessCopy(text)).toBe(false);
    expect(isBatchAllSuccessCopy('批量录入成功')).toBe(true);
  });

  it('M 可为 0，但仍写出跳过未完整 0', () => {
    const text = batchSubmitMessage(2, 0);
    expect(text).toContain('已录入 2');
    expect(text).toContain('跳过未完整 0');
  });
});
