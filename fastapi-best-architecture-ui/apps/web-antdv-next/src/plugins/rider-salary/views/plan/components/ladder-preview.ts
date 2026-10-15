import type { LadderTier } from '../../../types/plan';

export interface LadderSlice {
  amount: number;
  label: string;
}

export interface LadderProbe {
  amount: number;
  error: string;
  hitIndex: number;
  hitLabel: string;
  slices: LadderSlice[];
}

export interface QuantityPreview {
  amount: number;
  error: string;
  note: string;
  slices: LadderSlice[];
}

function money(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function tierRange(tier: LadderTier): string {
  const low = Number(tier.下限);
  if (tier.上限 === null || tier.上限 === undefined) return `${low} 及以上`;
  return `${low}（含）～ ${tier.上限}`;
}

export function previewLadder(
  value: number,
  mode: string,
  pricing: string,
  tiers: LadderTier[],
): LadderProbe {
  const amount = Number(value);
  if (!Number.isFinite(amount)) {
    return { amount: 0, error: '请填写数值', hitIndex: -1, hitLabel: '', slices: [] };
  }
  if (mode === '分段累进' && pricing === '固定金额') {
    return {
      amount: 0,
      error: '分段累进只支持按单价',
      hitIndex: -1,
      hitLabel: '',
      slices: [],
    };
  }
  if (!tiers.length) {
    return { amount: 0, error: '至少需要 1 档', hitIndex: -1, hitLabel: '', slices: [] };
  }

  const hitIndex = tiers.findIndex((tier) => {
    const low = Number(tier.下限);
    if (tier.上限 === null || tier.上限 === undefined) return amount >= low;
    return low <= amount && amount < Number(tier.上限);
  });

  if (mode === '全量落档') {
    if (hitIndex < 0) {
      return { amount: 0, error: '', hitIndex: -1, hitLabel: '未落入任何档位', slices: [] };
    }
    const tier = tiers[hitIndex]!;
    const rate = Number(tier.值);
    const total = pricing === '固定金额' ? rate : amount * rate;
    const label =
      pricing === '固定金额'
        ? `第 ${hitIndex + 1} 档固定金额`
        : `${amount} × 单价 ${rate}`;
    return {
      amount: money(total),
      error: '',
      hitIndex,
      hitLabel: `第 ${hitIndex + 1} 档 · ${tierRange(tier)} · 值 ${rate}`,
      slices: [{ amount: money(total), label }],
    };
  }

  if (mode === '分段累进') {
    const slices: LadderSlice[] = [];
    let total = 0;
    tiers.forEach((tier, index) => {
      const low = Number(tier.下限);
      if (amount <= low) return;
      const high = tier.上限 === null || tier.上限 === undefined ? amount : Math.min(amount, Number(tier.上限));
      if (high <= low) return;
      const span = high - low;
      const rate = Number(tier.值);
      const part = span * rate;
      total += part;
      const upperText = tier.上限 === null || tier.上限 === undefined || amount < Number(tier.上限)
        ? String(high)
        : String(tier.上限);
      slices.push({
        amount: money(part),
        label: `第 ${index + 1} 档 ${low}～${upperText}，跨度 ${span} × 单价 ${rate}`,
      });
    });
    const hitLabel = hitIndex < 0
      ? '未达到任何档位'
      : `最高落到第 ${hitIndex + 1} 档 · ${tierRange(tiers[hitIndex]!)} · 值 ${tiers[hitIndex]!.值}`;
    return { amount: money(total), error: '', hitIndex, hitLabel, slices };
  }

  return { amount: 0, error: '请选择全量落档或分段累进', hitIndex: -1, hitLabel: '', slices: [] };
}

export function previewOrderQuantity(options: {
  countField: boolean;
  fieldName: string;
  mode: string;
  orderCount: number;
  pricing: string;
  sample: LadderProbe;
  sampleValue: number;
  tiers: LadderTier[];
}): QuantityPreview {
  const count = Number(options.orderCount);
  if (!Number.isFinite(count) || count < 0) {
    return { amount: 0, error: '订单数量不能为负', note: '', slices: [] };
  }
  if (options.countField) {
    const probe = previewLadder(count, options.mode, options.pricing, options.tiers);
    return {
      amount: probe.amount,
      error: probe.error,
      note: probe.error || `把 ${count} 单当作「${options.fieldName}」代入阶梯`,
      slices: probe.slices,
    };
  }
  if (options.sample.error) {
    return { amount: 0, error: options.sample.error, note: '', slices: [] };
  }
  const total = money(options.sample.amount * count);
  return {
    amount: total,
    error: '',
    note: `每单 ${options.sample.amount.toFixed(2)} 元 × ${count} 单`,
    slices: options.sample.slices.map((slice) => ({
      amount: money(slice.amount * count),
      label: `${slice.label}，再 × ${count} 单`,
    })),
  };
}
