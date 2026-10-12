export interface CalcJobFailureItem {
  job_no: string;
  reason: string;
  rider_id: number;
}

export interface CalcJobSnapshot {
  done_count: number;
  error_message?: null | string;
  failed_count: number;
  failures?: CalcJobFailureItem[];
  status: string;
  success_count: number;
  total_count: number;
  warnings?: string[];
}

export interface CalcOutcome {
  level: 'error' | 'success' | 'warning';
  text: string;
}

const FINISHED = new Set(['failed', 'partial', 'succeeded']);

export function isCalcJobFinished(status: string): boolean {
  return FINISHED.has(status);
}

export function describeCalcJob(job: CalcJobSnapshot): CalcOutcome {
  if (job.status === 'failed') {
    return { level: 'error', text: job.error_message || '算薪失败' };
  }
  if (job.status === 'partial') {
    const reasons = (job.failures ?? [])
      .map((item) => `${item.job_no || item.rider_id}：${item.reason}`)
      .filter(Boolean)
      .join('；');
    const head = `成功 ${job.success_count} 人，失败 ${job.failed_count} 人`;
    return { level: 'warning', text: reasons ? `${head}。${reasons}` : head };
  }
  return { level: 'success', text: `已计算 ${job.success_count} 名骑手` };
}

export function calcProgressText(job: CalcJobSnapshot): string {
  return `正在计算 ${job.done_count}/${job.total_count}`;
}

export async function waitForCalcJob<T extends CalcJobSnapshot>(
  jobId: number,
  load: (id: number) => Promise<T>,
  options?: {
    intervalMs?: number;
    maxAttempts?: number;
    onTick?: (job: T) => void;
  },
): Promise<T> {
  const intervalMs = options?.intervalMs ?? 1000;
  const maxAttempts = options?.maxAttempts ?? 120;
  let last: T | undefined;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    last = await load(jobId);
    options?.onTick?.(last);
    if (isCalcJobFinished(last.status)) return last;
    if (intervalMs > 0) {
      await new Promise((resolve) => {
        setTimeout(resolve, intervalMs);
      });
    }
  }
  if (!last) {
    throw new Error('算薪作业不存在');
  }
  return last;
}
