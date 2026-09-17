import { describe, expect, it } from 'vitest';

import {
  countReverseTargets,
  isReversiblePayroll,
  reverseConfirmContent,
} from './reverse-confirm';

describe('reverse confirm counts', () => {
  it('只计本周期已定稿/已发薪条，不把草稿和已反冲算进去', () => {
    const counts = countReverseTargets([
      { kind: 'normal', reversed: false, rider_id: 1, status: 'finalized' },
      { kind: 'normal', reversed: false, rider_id: 2, status: 'paid' },
      { kind: 'normal', reversed: false, rider_id: 3, status: 'draft' },
      { kind: 'reversal', reversed: false, rider_id: 4, status: 'finalized' },
      { kind: 'normal', reversed: true, rider_id: 5, status: 'finalized' },
      { kind: 'normal', reversed: false, rider_id: 1, status: 'paid' },
    ]);
    expect(counts.reversal_count).toBe(3);
    expect(counts.rider_count).toBe(2);
  });

  it('确认文案同时写出单数和人数', () => {
    const text = reverseConfirmContent({ reversal_count: 4, rider_count: 2 });
    expect(text).toContain('4');
    expect(text).toContain('2');
    expect(text).toContain('人');
    expect(text).toMatch(/单|张/);
    expect(isReversiblePayroll({ kind: 'normal', reversed: false, status: 'draft' })).toBe(
      false,
    );
  });

  it('不得用窗内全量骑手数冒充将反冲人数', () => {
    const windowRiderCount = 10;
    const counts = countReverseTargets([
      { kind: 'normal', reversed: false, rider_id: 1, status: 'finalized' },
    ]);
    const text = reverseConfirmContent(counts);
    expect(counts.rider_count).toBe(1);
    expect(text).not.toContain(`涉及骑手 ${windowRiderCount} 人`);
  });
});
