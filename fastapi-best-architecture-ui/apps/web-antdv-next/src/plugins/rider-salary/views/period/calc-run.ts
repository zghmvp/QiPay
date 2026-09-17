import type { PayrollSummary } from '../../types/payroll';
import type { CalculatePeriodResult, PeriodWithPayrolls } from '../../types/period';

import {
  readCalcRun,
  rememberCalcRun,
  uniquePositiveIds,
} from '../../utils/last-calc-success';

export function pickThisRunPayrolls(
  payrolls: PayrollSummary[] | undefined,
  riderIds: number[],
): PayrollSummary[] {
  const ids = new Set(riderIds);
  if (!ids.size) return [];
  return (payrolls ?? []).filter((row) => ids.has(row.rider_id));
}

function idsFromResult(result?: CalculatePeriodResult | null): number[] {
  return uniquePositiveIds(result?.calculated_rider_ids);
}

function idsFromPeriod(period?: PeriodWithPayrolls): number[] {
  return uniquePositiveIds(period?.last_calc_success_ids);
}

export function deriveSuccessRiderIds(options: {
  failedRiderIds: number[];
  payrolls?: PayrollSummary[];
  result?: CalculatePeriodResult | null;
  targetRiderIds: null | number[];
}): number[] {
  const failed = new Set(options.failedRiderIds);
  const fromResult = idsFromResult(options.result);
  if (fromResult.length) {
    return fromResult.filter((id) => !failed.has(id));
  }
  if (options.targetRiderIds && options.targetRiderIds.length) {
    return uniquePositiveIds(options.targetRiderIds).filter((id) => !failed.has(id));
  }
  return uniquePositiveIds((options.payrolls ?? []).map((row) => row.rider_id)).filter(
    (id) => !failed.has(id),
  );
}

export function resolveThisRunRiderIds(options: {
  failedRiderIds: number[];
  lastResult?: CalculatePeriodResult | null;
  period?: PeriodWithPayrolls;
  periodId: number;
}): number[] {
  const apiIds = idsFromPeriod(options.period);
  if (apiIds.length) return apiIds;

  const fromResult = idsFromResult(options.lastResult);
  if (fromResult.length) return fromResult;

  const stored = readCalcRun(options.periodId);
  if (stored?.successRiderIds?.length) {
    return uniquePositiveIds(stored.successRiderIds);
  }

  const status = options.period?.last_calc_status;
  if (stored && status === 'done') {
    return deriveSuccessRiderIds({
      failedRiderIds: options.failedRiderIds,
      payrolls: options.period?.payrolls,
      result: options.lastResult,
      targetRiderIds: stored.targetRiderIds,
    });
  }
  return [];
}

export function persistCalcRun(options: {
  periodId: number;
  successRiderIds: number[];
  targetRiderIds: null | number[];
}) {
  rememberCalcRun({
    periodId: options.periodId,
    successRiderIds: uniquePositiveIds(options.successRiderIds),
    targetRiderIds: options.targetRiderIds,
    ts: Date.now(),
  });
}
