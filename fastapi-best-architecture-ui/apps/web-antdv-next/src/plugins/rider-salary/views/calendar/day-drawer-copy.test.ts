import { describe, expect, it } from 'vitest';

import {
  DAY_DRAWER_FORMULA_HINT,
  DAY_DRAWER_NET_CARD_HINT,
  DAY_DRAWER_NET_HINT,
} from './day-drawer-copy';

describe('day drawer net copy', () => {
  it('公式金额 / 净额写明周期项不落日、对账看条', () => {
    expect(DAY_DRAWER_NET_HINT).toContain('周期项');
    expect(DAY_DRAWER_NET_HINT).toContain('不落日');
    expect(DAY_DRAWER_NET_HINT).toContain('对账看');
    expect(DAY_DRAWER_NET_HINT).toContain('条');
    expect(DAY_DRAWER_FORMULA_HINT).toContain('周期项不落日');
    expect(DAY_DRAWER_NET_CARD_HINT).toContain('周期项不落日');
    expect(DAY_DRAWER_NET_CARD_HINT).toContain('对账看条');
  });
});
