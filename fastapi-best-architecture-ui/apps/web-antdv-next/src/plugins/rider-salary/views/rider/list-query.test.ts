import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { statusFromQuery, withStatusDefault } from './list-query';

const HERE = dirname(fileURLToPath(import.meta.url));

describe('骑手列表 status 深链', () => {
  it('只消费非空字符串', () => {
    expect(statusFromQuery('on_job')).toBe('on_job');
    expect(statusFromQuery(' resigned ')).toBe('resigned');
    expect(statusFromQuery('')).toBeUndefined();
    expect(statusFromQuery('   ')).toBeUndefined();
    expect(statusFromQuery(['on_job'])).toBeUndefined();
    expect(statusFromQuery(undefined)).toBeUndefined();
  });

  it('只给状态字段写默认值', () => {
    const schema = [
      { fieldName: 'keyword' },
      { fieldName: 'status' },
      { fieldName: 'employ_type' },
    ];
    const next = withStatusDefault(schema, 'on_job');
    expect(next[0]).toEqual({ fieldName: 'keyword' });
    expect(next[1]).toEqual({ defaultValue: 'on_job', fieldName: 'status' });
    expect(next[2]).toEqual({ fieldName: 'employ_type' });
    expect(schema[1]).toEqual({ fieldName: 'status' });
    expect(withStatusDefault(schema, undefined)).toBe(schema);
  });

  it('工作台在职骑手链接会被骑手页预筛', () => {
    const dashboard = readFileSync(
      resolve(HERE, '../dashboard/components/StatCards.vue'),
      'utf8',
    );
    const match = dashboard.match(/\/rider-salary\/rider\?status=([a-z_]+)/);
    expect(match?.[1]).toBe('on_job');
    const status = statusFromQuery(match?.[1]);
    const schema = withStatusDefault(
      [{ fieldName: 'status' }] as Array<{
        defaultValue?: string;
        fieldName: string;
      }>,
      status,
    );
    expect(schema[0]?.defaultValue).toBe('on_job');
  });

  it('骑手页接上查询参数，档案深链仍在', () => {
    const page = readFileSync(resolve(HERE, 'index.vue'), 'utf8');
    expect(page).toContain('statusFromQuery(route.query.status)');
    expect(page).toContain('withStatusDefault(querySchema, initialStatus)');
    expect(page).toContain('gridApi.formApi.setValues({ status: initialStatus })');
    expect(page).toContain('route.query.rider_id');
    expect(page).toContain('route.query.edit_id');
  });
});
