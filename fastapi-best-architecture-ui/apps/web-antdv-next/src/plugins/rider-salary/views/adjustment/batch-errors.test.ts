import { describe, expect, it } from 'vitest';

import { parseBatchRowErrors } from './batch-errors';

describe('parseBatchRowErrors', () => {
  it('一次取出全部行错误', () => {
    const error = {
      response: {
        data: {
          code: 400,
          data: {
            errors: [
              { reason: '骑手不存在', row: 1 },
              { reason: '科目不存在', row: 2 },
              { reason: '金额必须大于 0', row: 3 },
            ],
          },
          msg: '第 1 行：骑手不存在；第 2 行：科目不存在；第 3 行：金额必须大于 0',
        },
      },
    };
    expect(parseBatchRowErrors(error)).toEqual([
      { reason: '骑手不存在', row: 1 },
      { reason: '科目不存在', row: 2 },
      { reason: '金额必须大于 0', row: 3 },
    ]);
  });

  it('没有错误列表时返回空数组', () => {
    expect(parseBatchRowErrors({ response: { data: { msg: '失败' } } })).toEqual(
      [],
    );
    expect(parseBatchRowErrors(null)).toEqual([]);
  });
});
