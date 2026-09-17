/** CDP: ops-import-not-payroll — 导入完成 ≠ 出账；关向导仍找得到最近 job */
import {
  FIX_JOB_NO,
  IMPORT_NOT_PAYROLL_COPY,
  PARTIAL_FAIL_COPY,
  assertNotGreenCompleteAlone,
  assertPartialFailVisible,
  buildImportCsv,
  failedPeriodIdsFromJob,
  findLatestRecalcJob,
  siteMonth,
  uniqueOrderNo,
  wizardImport,
} from '../cycle1-lib.mjs';

export const name = 'ops-import-not-payroll';

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, siteCode, month } = siteMonth();

  await page.goto(`${config.adminUrl}/rider-salary/order`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });

  const offCsv = buildImportCsv({
    siteCode,
    jobNo: FIX_JOB_NO,
    day: `${month}-10`,
    orderNo: uniqueOrderNo('FIX_C1_OFF_'),
  });
  await wizardImport(page, { siteCode, csv: offCsv, autoRecalc: false });

  const notPayroll = page.getByTestId('import-not-payroll').first();
  await notPayroll.waitFor({ state: 'visible', timeout: 120000 });
  const copy = await notPayroll.innerText();
  if (!IMPORT_NOT_PAYROLL_COPY.test(copy)) {
    throw new Error(`结果步须写明「导入完成 ≠ 已出账」：${copy.slice(0, 200)}`);
  }
  const gotoCalc = page.getByTestId('import-goto-calculate').first();
  await gotoCalc.waitFor({ state: 'visible', timeout: 20000 });
  await helpers.shot(page, 'cdp-ops-import-not-payroll-result');
  await gotoCalc.click();
  await page.waitForURL(/\/rider-salary\/period\/\d+\/calculate/, { timeout: 30000 });

  await page.goto(`${config.adminUrl}/rider-salary/order`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  const lastEntry = page.getByTestId('order-last-recalc');
  await lastEntry.waitFor({ state: 'visible', timeout: 20000 });
  const lastCopy = await lastEntry.innerText();
  if (!IMPORT_NOT_PAYROLL_COPY.test(lastCopy) && !/重算/.test(lastCopy)) {
    throw new Error('关向导后导入页没有最近 job / 去算薪入口（order-last-recalc；须走 GET /recalc-jobs/latest）');
  }

  const onCsv = buildImportCsv({
    siteCode,
    jobNo: FIX_JOB_NO,
    day: `${month}-15`,
    orderNo: uniqueOrderNo('FIX_C1_ON_'),
  });
  await wizardImport(page, { siteCode, csv: onCsv, autoRecalc: true });
  const statusBox = page.getByTestId('import-recalc-status');
  await statusBox.waitFor({ state: 'visible', timeout: 120000 });
  const failedBox = page.getByTestId('import-recalc-failed');
  try {
    await failedBox.waitFor({ state: 'visible', timeout: 180000 });
  } catch {
    const txt = await statusBox.innerText();
    throw new Error(
      `自动重算硬失败不得纯绿「完成」（须见部分失败/失败人数）：${txt.slice(0, 300)}`,
    );
  }
  const failText = await failedBox.innerText();
  assertNotGreenCompleteAlone(failText);
  assertPartialFailVisible(failText);
  await page.keyboard.press('Escape').catch(() => {});

  await page.goto(
    `${config.adminUrl}/rider-salary/dashboard?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  const dashJob = page.getByTestId('dashboard-batch-job');
  const orderJob = page.getByTestId('order-last-recalc');
  const dashVisible = await dashJob.isVisible().catch(() => false);
  if (!dashVisible) {
    await page.goto(`${config.adminUrl}/rider-salary/order`, {
      waitUntil: 'networkidle',
      timeout: 60000,
    });
  }
  const found =
    (await dashJob.isVisible().catch(() => false)) ||
    (await orderJob.isVisible().catch(() => false));
  if (!found) {
    throw new Error(
      '关向导后工作台 dashboard-batch-job 与导入页 order-last-recalc 都找不到最近 job（须走 GET /recalc-jobs/latest）',
    );
  }

  const probed = await findLatestRecalcJob({
    apiUrl: config.apiUrl,
    token,
    siteId,
  });
  if (probed.http !== 200) {
    throw new Error(`GET /recalc-jobs/latest 须 HTTP 200（job 可空），实际 ${probed.http}`);
  }
  if (!probed.job?.id) {
    throw new Error(
      '自动重算后 GET /recalc-jobs/latest 返回 200 但 job 为空。合同是 { site_id, job }，刚导入不应为 null',
    );
  }
  if (PARTIAL_FAIL_COPY.test(probed.job.message || '') || probed.job.status === 'failed') {
    const pids = failedPeriodIdsFromJob(probed.job);
    if (pids.length) {
      await page.goto(`${config.adminUrl}/rider-salary/period/${pids[0]}/calculate`, {
        waitUntil: 'networkidle',
        timeout: 60000,
      });
      const calc = await page.getByTestId('period-calc-failed').innerText().catch(async () =>
        page.locator('body').innerText(),
      );
      if (!calc.includes(FIX_JOB_NO) && !/无生效方案/.test(calc)) {
        throw new Error(`算薪页未见 ${FIX_JOB_NO}：${calc.slice(0, 200)}`);
      }
    }
  }

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-import-not-payroll');
}
