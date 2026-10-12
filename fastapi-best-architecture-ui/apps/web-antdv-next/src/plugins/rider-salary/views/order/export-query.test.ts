import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { buildOrderExportQuery } from './export-query';

const pageSource = readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), 'index.vue'),
  'utf8',
);

describe('订单导出参数', () => {
  it('带上站点、骑手和日期，丢掉列表上的其他筛选项', () => {
    expect(
      buildOrderExportQuery({
        date_range: ['2026-09-01', '2026-09-30'],
        rider_id: 7,
        site_id: 2,
      }),
    ).toEqual({
      date_from: '2026-09-01',
      date_to: '2026-09-30',
      rider_id: 7,
      site_id: 2,
    });
  });

  it('没选站点时不带 site_id', () => {
    expect(buildOrderExportQuery({ site_id: undefined }).site_id).toBe(
      undefined,
    );
  });

  it('订单页有导出按钮，并走订单导出权限', () => {
    expect(pageSource).toContain("v-access:code=\"'rs:order:export'\"");
    expect(pageSource).toContain('exportOrdersApi');
    expect(pageSource).toContain('buildOrderExportQuery');
  });
});
