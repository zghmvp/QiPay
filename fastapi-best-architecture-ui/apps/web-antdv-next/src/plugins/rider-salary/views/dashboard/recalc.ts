import {
  calcProgressText,
  describeCalcJob,
  isCalcJobFinished,
  waitForCalcJob,
  type CalcJobSnapshot,
} from '../period/calc-progress';

export const STALE_RECALC_PERM = 'rs:period:calculate';
export const STALE_BLOCK_KEY = 'stale_periods';
export const STALE_LIST_PAGE_SIZE = 200;

const CALCULABLE_STATUS = new Set(['open', 'reopened']);
const MAX_LIST_PAGES = 50;

export interface StalePeriodTarget {
  label: string;
  periodId: number;
}

export interface StalePeriodPage {
  items: Record<string, unknown>[];
  total: number;
}

export interface RecalcRunResult {
  level: 'error' | 'info' | 'success' | 'warning';
  shouldRefresh: boolean;
  text: string;
}

interface ParsedPeriod extends StalePeriodTarget {
  status: string;
}

interface PeriodOutcome {
  label: string;
  ok: boolean;
  reason?: string;
  refresh: boolean;
  riders: number;
}

export function showStaleRecalc(blockKey: string, canCalculate: boolean): boolean {
  return blockKey === STALE_BLOCK_KEY && canCalculate;
}

export function stalePeriodListQuery(input: {
  month?: string;
  page: number;
  siteId?: null | number;
  size?: number;
}) {
  const query: {
    month?: string;
    page: number;
    site_id?: number;
    size: number;
    stale: true;
    status: string;
  } = {
    page: input.page,
    size: input.size ?? STALE_LIST_PAGE_SIZE,
    stale: true,
    status: 'open,reopened',
  };
  if (input.month) query.month = input.month;
  if (input.siteId) query.site_id = input.siteId;
  return query;
}

function positiveInt(value: unknown): null | number {
  if (typeof value === 'number' && Number.isInteger(value) && value > 0) {
    return value;
  }
  if (typeof value === 'string' && /^\d+$/.test(value)) {
    const parsed = Number(value);
    return parsed > 0 ? parsed : null;
  }
  return null;
}

function labelOf(item: Record<string, unknown>, periodId: number): string {
  if (typeof item.range === 'string' && item.range.trim()) return item.range.trim();
  const start = typeof item.start_date === 'string' ? item.start_date : '';
  const end = typeof item.end_date === 'string' ? item.end_date : '';
  if (start && end) return `${start}~${end}`;
  return `周期 ${periodId}`;
}

function parsePeriod(item: Record<string, unknown>): ParsedPeriod | null {
  const periodId = positiveInt(item.period_id) ?? positiveInt(item.id);
  if (!periodId) return null;
  return {
    label: labelOf(item, periodId),
    periodId,
    status: typeof item.status === 'string' ? item.status : '',
  };
}

function dedupe(rows: ParsedPeriod[]): ParsedPeriod[] {
  const seen = new Set<number>();
  const merged: ParsedPeriod[] = [];
  for (const row of rows) {
    if (seen.has(row.periodId)) continue;
    seen.add(row.periodId);
    merged.push(row);
  }
  return merged;
}

export async function resolveStaleTargets(input: {
  count: number;
  items: Record<string, unknown>[];
  listPage?: (page: number, size: number) => Promise<StalePeriodPage>;
}): Promise<{ skipped: string[]; targets: StalePeriodTarget[] }> {
  const preview = dedupe(
    input.items
      .map((item) => parsePeriod(item))
      .filter((item): item is ParsedPeriod => item !== null),
  );
  let merged = preview;
  if (input.count > preview.length && input.listPage) {
    const extra: ParsedPeriod[] = [];
    for (let page = 1; page <= MAX_LIST_PAGES; page += 1) {
      const result = await input.listPage(page, STALE_LIST_PAGE_SIZE);
      const batch = (result.items ?? [])
        .map((item) => parsePeriod(item))
        .filter((item): item is ParsedPeriod => item !== null);
      extra.push(...batch);
      if (batch.length < STALE_LIST_PAGE_SIZE) break;
      if (result.total > 0 && extra.length >= result.total) break;
    }
    merged = dedupe([...preview, ...extra]);
  }
  const targets: StalePeriodTarget[] = [];
  const skipped: string[] = [];
  for (const row of merged) {
    if (row.status && !CALCULABLE_STATUS.has(row.status)) {
      skipped.push(`${row.label} 当前状态不可重算`);
      continue;
    }
    targets.push({ label: row.label, periodId: row.periodId });
  }
  return { skipped, targets };
}

export function recalcProgressText(input: {
  done: number;
  job?: CalcJobSnapshot | null;
  label: string;
  phase: 'poll' | 'submit';
  total: number;
}): string {
  const head = `正在重算 ${input.done}/${input.total}`;
  if (input.phase === 'submit') return `${head}：正在提交 ${input.label}`;
  if (input.job) return `${head}：${input.label} ${calcProgressText(input.job)}`;
  return head;
}

export function errorText(error: unknown): string {
  if (error && typeof error === 'object') {
    const record = error as { message?: unknown; msg?: unknown };
    if (typeof record.msg === 'string' && record.msg.trim()) return record.msg.trim();
    if (typeof record.message === 'string' && record.message.trim()) {
      return record.message.trim();
    }
  }
  return '重算失败';
}

function summarize(
  outcomes: PeriodOutcome[],
  skipped: string[],
): RecalcRunResult {
  const ok = outcomes.filter((item) => item.ok);
  const bad = outcomes.filter((item) => !item.ok);
  const notes = [
    ...skipped,
    ...bad.map((item) => `${item.label}：${item.reason || '重算失败'}`),
  ];
  const shouldRefresh = outcomes.some((item) => item.refresh);
  if (!outcomes.length && !skipped.length) {
    return { level: 'warning', shouldRefresh: false, text: '没有可重算的周期' };
  }
  if (!outcomes.length) {
    return { level: 'warning', shouldRefresh: false, text: notes.join('；') };
  }
  const riders = ok.reduce((sum, item) => sum + item.riders, 0);
  if (!bad.length && !skipped.length) {
    return {
      level: 'success',
      shouldRefresh,
      text: `已重算 ${ok.length} 个周期，共 ${riders} 名骑手`,
    };
  }
  if (!ok.length) {
    return { level: 'error', shouldRefresh, text: notes.join('；') };
  }
  return {
    level: 'warning',
    shouldRefresh,
    text: `成功 ${ok.length} 个周期，未完成 ${bad.length + skipped.length} 个。${notes.join('；')}`,
  };
}

export async function runStaleRecalc(input: {
  calculate: (periodId: number) => Promise<{
    calculated: number;
    job_id?: null | number;
    queued: boolean;
  }>;
  intervalMs?: number;
  loadJob: (jobId: number) => Promise<CalcJobSnapshot>;
  onProgress?: (text: string) => void;
  skipped?: string[];
  targets: StalePeriodTarget[];
}): Promise<RecalcRunResult> {
  const outcomes: PeriodOutcome[] = [];
  const total = input.targets.length;
  let done = 0;
  for (const target of input.targets) {
    input.onProgress?.(
      recalcProgressText({
        done,
        label: target.label,
        phase: 'submit',
        total,
      }),
    );
    try {
      const created = await input.calculate(target.periodId);
      if (created.queued && created.job_id) {
        const job = await waitForCalcJob(created.job_id, input.loadJob, {
          intervalMs: input.intervalMs ?? 1000,
          onTick: (item) => {
            input.onProgress?.(
              recalcProgressText({
                done,
                job: item,
                label: target.label,
                phase: 'poll',
                total,
              }),
            );
          },
        });
        if (!isCalcJobFinished(job.status)) {
          outcomes.push({
            label: target.label,
            ok: false,
            reason: '仍在计算，请稍后刷新',
            refresh: true,
            riders: job.success_count,
          });
        } else if (job.status === 'succeeded') {
          outcomes.push({
            label: target.label,
            ok: true,
            refresh: true,
            riders: job.success_count,
          });
        } else {
          outcomes.push({
            label: target.label,
            ok: false,
            reason: describeCalcJob(job).text,
            refresh: true,
            riders: job.success_count,
          });
        }
      } else {
        outcomes.push({
          label: target.label,
          ok: true,
          refresh: true,
          riders: created.calculated,
        });
      }
    } catch (error) {
      outcomes.push({
        label: target.label,
        ok: false,
        reason: errorText(error),
        refresh: false,
        riders: 0,
      });
    }
    done += 1;
  }
  return summarize(outcomes, input.skipped ?? []);
}
