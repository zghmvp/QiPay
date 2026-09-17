/** CDP: ops-import-recalc-progress — 导入自动重算不得纯绿「完成」 */
import {
  FIX_JOB_NO,
  assertNotGreenCompleteAlone,
  assertPartialFailVisible,
  buildImportCsv,
  failedPeriodIdsFromJob,
  importCsv,
  siteMonth,
  uniqueOrderNo,
  waitRecalcJob,
} from '../cycle1-lib.mjs';

export const name = 'ops-import-recalc-progress';

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, siteCode, month } = siteMonth();

  await page.goto(`${config.adminUrl}/rider-salary/order`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  const importBtn = page.getByRole('button', { name: /^导入$/ }).first();
  await importBtn.click();
  await page.getByText('导入后自动重算').waitFor({ state: 'visible', timeout: 15000 });
  await helpers.shot(page, 'cdp-ops-import-recalc-progress-wizard');

  const csv = buildImportCsv({
    siteCode,
    jobNo: FIX_JOB_NO,
    day: `${month}-15`,
    orderNo: uniqueOrderNo('FIX_C1_RC_'),
  });
  const result = await importCsv(config.apiUrl, token, {
    siteId,
    csv,
    autoRecalc: true,
    filename: 'cycle1-recalc-progress.csv',
  });
  const jobId = result?.recalc_job_id;
  if (!jobId) {
    throw new Error('自动重算开启后导入结果缺少 recalc_job_id');
  }
  const job = await waitRecalcJob(config.apiUrl, token, jobId);
  assertNotGreenCompleteAlone(job.message, { job });
  assertPartialFailVisible('', job);

  await page.keyboard.press('Escape').catch(() => {});
  const pids = failedPeriodIdsFromJob(job);
  const periodId = pids[0];
  if (!periodId) {
    throw new Error('部分失败 job 未带 period_id，无法进算薪页核对无方案骑手');
  }
  await page.goto(`${config.adminUrl}/rider-salary/period/${periodId}/calculate`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  const failedBox = page.getByTestId('period-calc-failed');
  await failedBox.waitFor({ state: 'visible', timeout: 20000 });
  const failText = await failedBox.innerText();
  if (!failText.includes(FIX_JOB_NO) && !/无生效方案/.test(failText)) {
    throw new Error(`算薪页未见无方案骑手 ${FIX_JOB_NO}：${failText.slice(0, 200)}`);
  }
  if (/重算状态：完成/.test(failText) && !/部分失败|失败/.test(failText)) {
    throw new Error('夹具含无方案骑手时不得用绿「完成」冒充已出账');
  }
  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-import-recalc-progress');
}
