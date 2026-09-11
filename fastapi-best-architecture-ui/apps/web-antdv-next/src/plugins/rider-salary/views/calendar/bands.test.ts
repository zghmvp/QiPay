import { describe, expect, it } from 'vitest';

import { slicesForWeek, splitPlanBandsByWeek } from './bands';

const BAND_A = {
  color: '#1677ff',
  end: '2026-09-15',
  plan_version_id: 12,
  short_name: '底薪A',
  start: '2026-09-01',
};
const BAND_B = {
  color: '#fa8c16',
  end: '2026-09-30',
  plan_version_id: 15,
  short_name: '阶梯B',
  start: '2026-09-16',
};

describe('splitPlanBandsByWeek', () => {
  it('按周切开、月中换方案断开换色、跨周续接加 ↳', () => {
    const slices = splitPlanBandsByWeek('2026-09', [BAND_A, BAND_B]);

    expect(slices).toHaveLength(6);

    const week0 = slicesForWeek(slices, 0);
    expect(week0).toEqual([
      expect.objectContaining({
        colEnd: 6,
        colStart: 1,
        color: '#1677ff',
        continued: false,
        label: '底薪A',
        start: '2026-09-01',
        end: '2026-09-06',
      }),
    ]);

    const week1 = slicesForWeek(slices, 1);
    expect(week1[0]).toMatchObject({
      colEnd: 6,
      colStart: 0,
      color: '#1677ff',
      continued: true,
      label: '↳ 底薪A',
    });

    const week2 = slicesForWeek(slices, 2);
    expect(week2).toHaveLength(2);
    expect(week2[0]).toMatchObject({
      colEnd: 1,
      colStart: 0,
      color: '#1677ff',
      continued: true,
      end: '2026-09-15',
      start: '2026-09-14',
    });
    expect(week2[1]).toMatchObject({
      colEnd: 6,
      colStart: 2,
      color: '#fa8c16',
      continued: false,
      label: '阶梯B',
      start: '2026-09-16',
    });

    const week3 = slicesForWeek(slices, 3);
    expect(week3[0]).toMatchObject({
      colEnd: 6,
      colStart: 0,
      color: '#fa8c16',
      continued: true,
      label: '↳ 阶梯B',
    });

    const week4 = slicesForWeek(slices, 4);
    expect(week4[0]).toMatchObject({
      colEnd: 2,
      colStart: 0,
      color: '#fa8c16',
      continued: true,
      end: '2026-09-30',
      label: '↳ 阶梯B',
    });

    expect(slicesForWeek(slices, 5)).toHaveLength(0);
  });

  it('无方案或无颜色的区间不画带', () => {
    const slices = splitPlanBandsByWeek('2026-09', [
      { color: null, end: '2026-09-10', plan_version_id: null, start: '2026-09-01' },
      { color: '', end: '2026-09-10', plan_version_id: 1, short_name: '空', start: '2026-09-01' },
    ]);
    expect(slices).toHaveLength(0);
  });
});
