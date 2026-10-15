import { describe, expect, it } from 'vitest';

import { previewLadder, previewOrderQuantity } from './ladder-preview';

const TIERS = [
  { 上限: 300, 下限: 0, 值: 5 },
  { 上限: 600, 下限: 300, 值: 5.5 },
  { 上限: null, 下限: 600, 值: 6 },
];

describe('previewLadder', () => {
  it('全量落档按单价命中所在档', () => {
    const hit = previewLadder(420, '全量落档', '按单价', TIERS);
    expect(hit.hitIndex).toBe(1);
    expect(hit.amount).toBeCloseTo(420 * 5.5, 2);
    expect(previewLadder(300, '全量落档', '按单价', TIERS).amount).toBeCloseTo(300 * 5.5, 2);
    expect(previewLadder(600, '全量落档', '按单价', TIERS).hitIndex).toBe(2);
  });

  it('分段累进按跨度累加', () => {
    const hit = previewLadder(420, '分段累进', '按单价', TIERS);
    expect(hit.amount).toBeCloseTo(300 * 5 + 120 * 5.5, 2);
    expect(hit.slices).toHaveLength(2);
    expect(previewLadder(0, '分段累进', '按单价', TIERS).amount).toBe(0);
  });

  it('分段累进不支持固定金额', () => {
    expect(previewLadder(100, '分段累进', '固定金额', TIERS).error).toContain('按单价');
  });
});

describe('previewOrderQuantity', () => {
  it('单量字段直接把数量代入阶梯', () => {
    const sample = previewLadder(5, '全量落档', '按单价', TIERS);
    const result = previewOrderQuantity({
      countField: true,
      fieldName: '周期有效单量',
      mode: '全量落档',
      orderCount: 420,
      pricing: '按单价',
      sample,
      sampleValue: 5,
      tiers: TIERS,
    });
    expect(result.amount).toBeCloseTo(420 * 5.5, 2);
    expect(result.note).toContain('420');
  });

  it('非单量字段用单笔金额乘订单数量', () => {
    const distance = [
      { 上限: 3, 下限: 0, 值: 1 },
      { 上限: null, 下限: 3, 值: 2 },
    ];
    const sample = previewLadder(5, '全量落档', '固定金额', distance);
    const result = previewOrderQuantity({
      countField: false,
      fieldName: '配送距离',
      mode: '全量落档',
      orderCount: 100,
      pricing: '固定金额',
      sample,
      sampleValue: 5,
      tiers: distance,
    });
    expect(sample.amount).toBe(2);
    expect(result.amount).toBe(200);
    expect(result.note).toContain('100 单');
  });
});
