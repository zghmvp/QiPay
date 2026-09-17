/** CDP: ops-lock-preflight-hard-fail — 有完成单未算出则锁不住 */
export const name = 'ops-lock-preflight-hard-fail';

const HARD_FAIL_JOB_NO = process.env.CDP_LOCK_HARD_FAIL_JOB_NO || 'FIX_C17_LOCK';
const HARD_FAIL_COPY = /锁账中止|无生效方案|未算出|缺送达|从未成功/;
const STALE_COPY = /存在需重算的薪资结果|请先重算/;

function periodHasStaleDrafts(detail, listRow) {
  const staleCount = Number(detail?.stale_count ?? listRow?.stale_count ?? 0);
  const payrolls = detail?.payrolls || [];
  return staleCount > 0 || payrolls.some((row) => row.stale === true);
}

async function fetchPeriodDetail(apiUrl, headers, periodId) {
  const res = await fetch(`${apiUrl}/api/v1/rider-salary/periods/${periodId}`, {
    headers,
  });
  if (!res.ok) {
    throw new Error(`读取周期 ${periodId} 失败：HTTP ${res.status}`);
  }
  return (await res.json())?.data;
}

/**
 * 只消费种子：独立骑手级开放周期（FIX_C17_LOCK），零 stale draft。
 * 禁止锁「本站本月第一个 open 周期」、禁止在本 spec 里 generate 个人周期。
 */
async function resolveHardFailPeriod({ apiUrl, headers, siteId, month }) {
  const envId = process.env.CDP_LOCK_HARD_FAIL_PERIOD_ID;
  const listRes = await fetch(
    `${apiUrl}/api/v1/rider-salary/periods?site_id=${siteId}&month=${month}&page=1&size=50`,
    { headers },
  );
  const items = (await listRes.json())?.data?.items || [];

  let candidate = null;
  if (envId) {
    candidate =
      items.find((row) => String(row.id) === String(envId)) || {
        id: Number(envId),
      };
  } else {
    candidate = items.find(
      (row) =>
        (row.status === 'open' || row.status === 'reopened') &&
        row.rider_job_no === HARD_FAIL_JOB_NO,
    );
  }

  if (!candidate?.id) {
    throw new Error(
      `未找到无 stale 硬失败周期（工号 ${HARD_FAIL_JOB_NO}）。请先运行 node scripts/cdp/seed-xiaoxiang-fixtures.mjs`,
    );
  }

  const detail = await fetchPeriodDetail(apiUrl, headers, candidate.id);
  const status = detail?.status || candidate.status;
  if (status !== 'open' && status !== 'reopened') {
    throw new Error(
      `硬失败夹具周期 ${candidate.id} 状态为 ${status}，须为开放周期`,
    );
  }
  if (periodHasStaleDrafts(detail, candidate)) {
    throw new Error(
      `夹具被 stale 短路，须灌无 stale 硬失败周期（period_id=${candidate.id} stale_count=${detail?.stale_count ?? candidate.stale_count}）`,
    );
  }
  return { id: candidate.id, detail };
}

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const headers = {
    Authorization: `Bearer ${admin.access_token}`,
    'Content-Type': 'application/json',
  };
  const siteId = process.env.CDP_SITE_ID || '13';
  const month = process.env.CDP_MONTH || '2026-09';

  const { id: periodId } = await resolveHardFailPeriod({
    apiUrl: config.apiUrl,
    headers,
    siteId,
    month,
  });

  const lockRes = await fetch(
    `${config.apiUrl}/api/v1/rider-salary/periods/${periodId}/lock`,
    {
      method: 'POST',
      headers,
      body: JSON.stringify({ reason: 'CDP 锁账硬拦' }),
    },
  );
  const lockJson = await lockRes.json();
  const errors = lockJson?.data?.errors;
  const msg = `${lockJson?.msg || ''} ${JSON.stringify(lockJson?.data || {})}`;
  if (lockRes.ok && lockJson?.code === 200) {
    throw new Error('FIX_C17 类有单未算出周期不应锁账成功');
  }
  if (STALE_COPY.test(msg) && !HARD_FAIL_COPY.test(msg)) {
    throw new Error(
      `夹具被 stale 短路，须灌无 stale 硬失败周期：${msg.slice(0, 300)}`,
    );
  }
  if (!HARD_FAIL_COPY.test(msg)) {
    throw new Error(`锁账失败文案缺少同口径中文：${msg.slice(0, 300)}`);
  }
  if (Array.isArray(errors) && errors.length) {
    const blob = errors.join(' ');
    if (!new RegExp(`${HARD_FAIL_JOB_NO}|\\d{4}-\\d{2}-\\d{2}|无生效方案|未算出|缺送达|从未成功`).test(blob)) {
      throw new Error(`锁账 errors 未含工号或日期：${blob.slice(0, 300)}`);
    }
  }

  const after = await fetch(
    `${config.apiUrl}/api/v1/rider-salary/periods/${periodId}`,
    { headers },
  );
  const status = (await after.json())?.data?.status;
  if (status === 'locked' || status === 'paid') {
    throw new Error(`锁账被拒绝后状态仍变为 ${status}`);
  }

  await page.goto(`${config.adminUrl}/rider-salary/period`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-lock-preflight-hard-fail');
}
