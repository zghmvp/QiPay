import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { buildCalendarMonthExport } from './month-export';

const pageSource = readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), 'index.vue'),
  'utf8',
);

describe('月历当月明细导出', () => {
  it('半月结的 9 月只生成一次导出参数', () => {
    const params = buildCalendarMonthExport({
      month: '2026-09',
      riderId: 7,
      siteId: 2,
    });
    expect(params).toEqual({
      month: '2026-09',
      rider_id: 7,
      site_id: 2,
    });
    expect(Array.isArray(params)).toBe(false);
  });

  it('站点和骑手缺一个就不导出', () => {
    expect(
      buildCalendarMonthExport({ month: '2026-09', riderId: 7 }),
    ).toBeUndefined();
    expect(
      buildCalendarMonthExport({ month: '2026-09', siteId: 2 }),
    ).toBeUndefined();
  });

  it('月历按钮调用按月导出，不再按周期循环下载', () => {
    expect(pageSource).toContain('exportMonthDetailApi');
    expect(pageSource).toContain('buildCalendarMonthExport');
    expect(pageSource).not.toContain('exportPeriodApi');
    expect(pageSource).not.toContain('for (const period of periods)');
  });
});