const JOB_KEY = 'qipay:last-recalc-job';
const IMPORT_KEY = 'qipay:last-import-calc';

export interface LastRecalcJobRef {
  jobId: number;
  siteId: number;
  ts: number;
}

export interface LastImportCalcRef {
  periodIds: number[];
  siteId: number;
  ts: number;
}

function readJson<T>(key: string): null | T {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

export function rememberRecalcJob(siteId: number, jobId: number) {
  if (!siteId || !jobId) return;
  const payload: LastRecalcJobRef = { jobId, siteId, ts: Date.now() };
  localStorage.setItem(JOB_KEY, JSON.stringify(payload));
}

export function readLastRecalcJob(siteId?: number): LastRecalcJobRef | null {
  const parsed = readJson<LastRecalcJobRef>(JOB_KEY);
  if (!parsed?.jobId || !parsed.siteId) return null;
  if (siteId && parsed.siteId !== siteId) return null;
  return parsed;
}

export function rememberImportCalcTarget(siteId: number, periodIds: number[]) {
  if (!siteId) return;
  const payload: LastImportCalcRef = {
    periodIds: periodIds.filter((n) => Number.isFinite(n) && n > 0),
    siteId,
    ts: Date.now(),
  };
  localStorage.setItem(IMPORT_KEY, JSON.stringify(payload));
}

export function readLastImportCalcTarget(
  siteId?: number,
): LastImportCalcRef | null {
  const parsed = readJson<LastImportCalcRef>(IMPORT_KEY);
  if (!parsed?.siteId) return null;
  if (siteId && parsed.siteId !== siteId) return null;
  return parsed;
}
