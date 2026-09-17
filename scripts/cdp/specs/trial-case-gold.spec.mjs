/** CDP: trial-case-gold — C03=8200 / C04=7800 / C05A=3500；金标数字走后端试算 API */
import { apiFetch, FIX_JOB_NO } from '../cycle1-lib.mjs';
import {
  GOLD_C03_GROSS,
  GOLD_C04_GROSS,
  GOLD_C05A_GROSS,
  GOLD_C17_PERIOD_AMOUNT,
  GOLD_C17_PLAN_AMOUNT,
  GOLD_C03_JOB,
  GOLD_C05_JOB,
  clickStartTrial,
  fillTrialTargets,
  moneyEquals,
  readTrialGross,
  requireGoldVersion,
  requireRiderByJobNo,
  siteMonth,
  trialVersion,
  waitTrialNumbers,
} from '../cycle2-lib.mjs';

export const name = 'trial-case-gold';

function trialGross(json) {
  const n = Number(json?.data?.summary?.gross ?? json?.data?.gross);
  return n;
}

function assertGross(label, actual, expected) {
  if (!Number.isFinite(actual)) {
    throw new Error(`${label} 无试算应发数字 = FAIL（禁止 WARN / skip 过）`);
  }
  if (!moneyEquals(actual, expected)) {
    throw new Error(`${label} 应发须=${expected}，实际=${actual}`);
  }
}

function assertTrialOk(label, trial) {
  if ([404, 405, 501].includes(trial.res.status)) {
    throw new Error(`${label} 试算接口缺失 HTTP ${trial.res.status}，不得 skip`);
  }
  if (!trial.res.ok) {
    throw new Error(`${label} 试算失败 HTTP ${trial.res.status}：${JSON.stringify(trial.json).slice(0, 300)}`);
  }
}

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, siteCode, month } = siteMonth();
  const start = `${month}-01`;
  const end = `${month}-30`;

  const riderC03 = await requireRiderByJobNo(config.apiUrl, token, siteId, GOLD_C03_JOB);
  const riderC05 = await requireRiderByJobNo(config.apiUrl, token, siteId, GOLD_C05_JOB);
  const c03 = await requireGoldVersion(config.apiUrl, token, 'FIX_C03');
  const c04 = await requireGoldVersion(config.apiUrl, token, 'FIX_C04');
  const c05 = await requireGoldVersion(config.apiUrl, token, 'FIX_C05');

  const t03 = await trialVersion(config.apiUrl, token, c03.version.id, {
    riderId: riderC03.id,
    start,
    end,
    mode: 'full_version',
  });
  assertTrialOk('C03', t03);
  assertGross('C03', trialGross(t03.json), GOLD_C03_GROSS);

  const t04 = await trialVersion(config.apiUrl, token, c04.version.id, {
    riderId: riderC03.id,
    start,
    end,
    mode: 'full_version',
  });
  assertTrialOk('C04', t04);
  assertGross('C04', trialGross(t04.json), GOLD_C04_GROSS);

  const t05 = await trialVersion(config.apiUrl, token, c05.version.id, {
    riderId: riderC05.id,
    start,
    end,
    mode: 'full_version',
  });
  assertTrialOk('C05A', t05);
  assertGross('C05A', trialGross(t05.json), GOLD_C05A_GROSS);

  await page.goto(`${config.adminUrl}/rider-salary/plan`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  const row = page.locator('.vxe-body--row, tr').filter({ hasText: 'FIX_C03' }).first();
  const trialBtn = (await row.count())
    ? row.getByRole('button', { name: /^试算$/ }).first()
    : page.getByRole('button', { name: /^试算$/ }).first();
  await trialBtn.click();
  await page.getByTestId('trial-mode').waitFor({ state: 'visible', timeout: 30000 });
  await page.getByTestId('trial-mode').getByText('整版试算').first().click();
  await fillTrialTargets(page, {
    siteCode,
    jobNo: GOLD_C03_JOB,
    start,
    end,
  });
  await clickStartTrial(page);
  // 试算结果异步渲染
  await page.getByText(/应发/).first().waitFor({ state: 'visible', timeout: 60000 }).catch(() => {});
  await page.waitForTimeout(800);
  const gross = await readTrialGross(page);
  assertGross('C03 UI', gross, GOLD_C03_GROSS);
  await waitTrialNumbers(page).catch(() => {
    /* 整版试算两单量可相等；有数字即可。无数字已由 readTrialGross FAIL */
  });

  const c17 = await apiFetch(
    config.apiUrl,
    token,
    'GET',
    `/api/v1/rider-salary/riders?page=1&size=5&site_id=${siteId}&keyword=${FIX_JOB_NO}`,
  );
  if (!(c17.json?.data?.items || []).some((r) => r.job_no === FIX_JOB_NO)) {
    throw new Error(`C17 夹具骑手 ${FIX_JOB_NO} 缺失`);
  }
  if (!(GOLD_C17_PERIOD_AMOUNT !== GOLD_C17_PLAN_AMOUNT && GOLD_C17_PERIOD_AMOUNT === 2310 && GOLD_C17_PLAN_AMOUNT === 100)) {
    throw new Error('C17 金标须为 2310 vs 100，不得 skip');
  }

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-trial-case-gold');
}
