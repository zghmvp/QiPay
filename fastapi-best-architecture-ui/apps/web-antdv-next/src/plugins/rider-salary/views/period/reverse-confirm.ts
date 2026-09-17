import type { PayrollSummary } from '../../types/payroll';

export interface ReversePreflightCounts {
  confirm_hint?: string;
  reversal_count: number;
  rider_count: number;
}

export function isReversiblePayroll(payroll: {
  kind?: null | string;
  reversed?: boolean;
  status?: null | string;
}): boolean {
  if (payroll.kind === 'reversal') return false;
  if (payroll.reversed) return false;
  return payroll.status === 'finalized' || payroll.status === 'paid';
}

/** 以后端即将实际反冲的已定稿/已发薪条为准，不得抄列表 rider_count。 */
export function countReverseTargets(
  payrolls: Array<
    Pick<PayrollSummary, 'kind' | 'reversed' | 'rider_id' | 'status'>
  >,
): ReversePreflightCounts {
  const targets = payrolls.filter((row) => isReversiblePayroll(row));
  const riders = new Set<number>();
  for (const row of targets) {
    const riderId = Number(row.rider_id);
    if (Number.isFinite(riderId) && riderId > 0) riders.add(riderId);
  }
  return {
    reversal_count: targets.length,
    rider_count: riders.size,
  };
}

export function reverseConfirmContent(counts: ReversePreflightCounts): string {
  const hint = counts.confirm_hint?.trim();
  if (
    hint &&
    /\d/.test(hint) &&
    hint.includes('人') &&
    (hint.includes('单') || hint.includes('张'))
  ) {
    return hint;
  }
  return (
    `本操作将生成反冲薪资单 ${counts.reversal_count} 张，涉及骑手 ${counts.rider_count} 人。` +
    '原单将标记已反冲，周期进入补发中。确认继续？'
  );
}
