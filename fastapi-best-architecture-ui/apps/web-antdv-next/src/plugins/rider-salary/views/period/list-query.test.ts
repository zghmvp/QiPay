import { describe, expect, it } from 'vitest';

import {
  STALE_PERIOD_STATUSES,
  buildPeriodListQuery,
  joinStatusQuery,
  omitStaleQuery,
  parseStaleFlag,
  parseStatusQuery,
} from './list-query';

describe('周期列表查询参数', () => {
  it('深链能同时带上开放和补发中', () => {
    expect(parseStatusQuery('open,reopened')).toEqual(['open', 'reopened']);
    expect(parseStatusQuery(['open', 'reopened'])).toEqual([
      'open',
      'reopened',
    ]);
    expect([...STALE_PERIOD_STATUSES]).toEqual(['open', 'reopened']);
    expect(parseStaleFlag('1')).toBe(true);
    expect(parseStaleFlag('true')).toBe(true);
    expect(parseStaleFlag('0')).toBe(false);
  });

  it('需重算筛选把状态和 stale 交给服务端', () => {
    const query = buildPeriodListQuery({
      onlyStale: true,
      page: 2,
      size: 2,
      status: ['open', 'reopened'],
    });
    expect(query).toEqual({
      page: 2,
      size: 2,
      status: 'open,reopened',
      stale: true,
    });
    expect(joinStatusQuery('open')).toBe('open');
    expect(
      buildPeriodListQuery({ onlyStale: false, page: 1, size: 20 }),
    ).toEqual({
      page: 1,
      size: 20,
    });
  });

  it('关掉需重算提示时去掉 stale，status 仍留在地址栏', () => {
    const current = {
      id: '12',
      status: 'open,reopened',
      stale: '1',
    };
    const next = omitStaleQuery(current);
    expect(next).toEqual({ id: '12', status: 'open,reopened' });
    expect(next).not.toHaveProperty('stale');
    expect(current.stale).toBe('1');
    expect(parseStaleFlag(next.stale)).toBe(false);
    expect(parseStatusQuery(next.status)).toEqual(['open', 'reopened']);
  });
});
