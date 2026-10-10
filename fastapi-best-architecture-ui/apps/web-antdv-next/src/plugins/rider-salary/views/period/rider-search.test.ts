import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import {
  CALCULATE_RIDER_ID_LIMIT,
  LEGACY_RIDER_PAGE_SIZE,
  RIDER_REMOTE_PAGE_SIZE,
  buildRiderSearchQuery,
  filterRidersByKeyword,
  mergeRiderOptions,
  pinSelectedRiders,
  ridersByNewestFirst,
  supplementCalculateParam,
  toRiderOption,
} from './rider-search';

const modalSource = readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), 'components/CalculateModal.vue'),
  'utf8',
);

describe('算薪弹窗骑手远程搜索', () => {
  it('300 人站点能搜到第 250 名，旧的前 200 名列表选不到', () => {
    const riders = ridersByNewestFirst(300);
    const target = riders[249];
    if (!target) throw new Error('缺少第 250 名骑手');
    expect(target).toEqual({ id: 51, job_no: 'R0051', name: '骑手51' });

    const firstPage = riders.slice(0, LEGACY_RIDER_PAGE_SIZE);
    expect(firstPage.some((item) => item.id === target.id)).toBe(false);

    const query = buildRiderSearchQuery({
      keyword: target.job_no,
      siteId: 9,
    });
    expect(query).toEqual({
      keyword: 'R0051',
      page: 1,
      site_id: 9,
      size: RIDER_REMOTE_PAGE_SIZE,
    });
    expect(query.size).toBeLessThan(LEGACY_RIDER_PAGE_SIZE);

    const found = filterRidersByKeyword(riders, query.keyword ?? '').slice(
      0,
      query.size,
    );
    expect(found).toEqual([target]);
    expect(toRiderOption(target)).toEqual({
      label: 'R0051 骑手51',
      value: 51,
    });
  });

  it('空关键字不传 keyword，已选骑手在换词后仍留在选项里', () => {
    expect(buildRiderSearchQuery({ keyword: '  ', siteId: 3 })).toEqual({
      page: 1,
      site_id: 3,
      size: RIDER_REMOTE_PAGE_SIZE,
    });

    const pinned = pinSelectedRiders(
      [51],
      [{ label: 'R0051 骑手51', value: 51 }],
    );
    const merged = mergeRiderOptions(pinned, [
      { label: 'R0300 骑手300', value: 300 },
    ]);
    expect(merged.map((item) => item.value)).toEqual([51, 300]);
    expect(pinSelectedRiders([7], [])).toEqual([{ label: '7', value: 7 }]);
  });

  it('超过单次上限时改为计算全部骑手', () => {
    expect(supplementCalculateParam([51])).toEqual({ rider_ids: [51] });
    expect(supplementCalculateParam([])).toEqual({ rider_ids: null });
    expect(
      supplementCalculateParam(
        Array.from({ length: CALCULATE_RIDER_ID_LIMIT + 1 }, (_, i) => i + 1),
      ),
    ).toEqual({ rider_ids: null });
  });

  it('弹窗走远程搜索，不再写死拉取 200 人', () => {
    expect(modalSource).toContain('buildRiderSearchQuery');
    expect(modalSource).toContain(':filter-option="false"');
    expect(modalSource).toContain('@search="onSearch"');
    expect(modalSource).not.toContain('size: 200');
    expect(modalSource).not.toContain('size:200');
  });
});
