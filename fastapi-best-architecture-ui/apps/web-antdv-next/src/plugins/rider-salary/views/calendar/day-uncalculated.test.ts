import { describe, expect, it } from 'vitest';

import type { CalendarDayDetail } from '../../types/calendar';

import {
  DAY_UNCALCULATED_DEDUCT_HINT,
  DAY_UNCALCULATED_HINT,
  DAY_UNCALCULATED_HIT_HINT,
  dayFormulaMainText,
  isUncalculatedDay,
  orderHitEmptyText,
} from './day-uncalculated';

function detail(
  patch: Partial<CalendarDayDetail> & { has_daily_cache?: boolean },
): CalendarDayDetail & { has_daily_cache?: boolean } {
  return {
    adjustments: [],
    daily_items: [],
    date: '2026-09-12',
    day_status: 'has_data',
    orders: [
      {
        details: [],
        distance_km: 1,
        id: 1,
        order_no: 'A1',
        order_time: '2026-09-12 10:00:00',
        status: 'completed',
        weight_jin: 1,
      },
    ],
    totals: {
      formula_amount: '0.00',
      manual_bonus: '0.00',
      manual_penalty: '0.00',
      net: '0.00',
      order_count: 1,
    },
    ...patch,
  };
}

describe('uncalculated day drawer', () => {
  it('有完成单、无 cache 时主数字是 — 并写出未算薪', () => {
    const day = detail({ has_daily_cache: false });
    expect(isUncalculatedDay(day)).toBe(true);
    expect(dayFormulaMainText(day)).toBe('—');
    expect(dayFormulaMainText(day)).not.toBe('0.00');
    expect(orderHitEmptyText(day)).toBe(DAY_UNCALCULATED_HIT_HINT);
    expect(orderHitEmptyText(day)).toContain('尚未进本次算薪');
    expect(DAY_UNCALCULATED_HINT).toContain('未算薪');
    expect(DAY_UNCALCULATED_DEDUCT_HINT).toContain('代扣不进日手工');
  });

  it('无显式 cache 时按无命中+公式 0 推断未算薪', () => {
    expect(isUncalculatedDay(detail({}))).toBe(true);
  });

  it('已有 cache 或已有命中项时不把 0 读成未算薪空态', () => {
    expect(isUncalculatedDay(detail({ has_daily_cache: true }))).toBe(false);
    expect(
      isUncalculatedDay(
        detail({
          orders: [
            {
              details: [{ amount: '1.00', subject: '提成' }],
              distance_km: 1,
              id: 1,
              order_no: 'A1',
              order_time: '2026-09-12 10:00:00',
              status: 'completed',
              weight_jin: 1,
            },
          ],
          totals: {
            formula_amount: '1.00',
            manual_bonus: '0.00',
            manual_penalty: '0.00',
            net: '1.00',
            order_count: 1,
          },
        }),
      ),
    ).toBe(false);
    expect(orderHitEmptyText(detail({ has_daily_cache: true }))).toBe('无命中项');
  });
});
