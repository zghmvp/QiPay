/** CDP: ops-import-skip-errors-not-all-success — 跳过错误行半成功必须说真话
 * 必须走向导 + 勾选跳过错误行。failed_rows > 0 仍「全部导入成功」= FAIL。
 * 把本席写成「仍 422」= FAIL。禁止 API importCsv 绿替。
 */
import {
  IMPORT_NOT_PAYROLL_COPY,
  MUST4_COMPLETE_HOOKS,
  MUST4_RESULT_HOOKS,
  MUST4_WIZARD_HOOKS,
  SKIP_ERRORS_LABEL,
  assertHalfSuccessVisible,
  assertLockedGoldUnchanged,
  assertNoImportCsvGreen,
  assertSkipErrorsCsvExists,
  openImportWizard,
  pickAntOption,
  requireHooks,
  siteMonth,
} from '../cycle14-lib.mjs';

export const name = 'ops-import-skip-errors-not-all-success';

export async function run({ page, helpers, config }) {
  assertLockedGoldUnchanged();
  assertNoImportCsvGreen();
  const csv = assertSkipErrorsCsvExists();
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const { siteCode } = siteMonth();

  let importResponse = null;
  page.on('response', async (res) => {
    if (res.request().method() === 'POST' && /\/orders\/import/.test(res.url())) {
      importResponse = res;
      try {
        res._cycle14BodyText = await res.text();
      } catch {
        res._cycle14BodyText = '';
      }
    }
  });

  await page.goto(`${config.adminUrl}/rider-salary/order`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  const dialog = await openImportWizard(page);
  await requireHooks(
    page,
    MUST4_WIZARD_HOOKS,
    '未见 ops-import-skip-errors-not-all-success / import-skip-errors。钩子缺失即红，不得 skip。禁止走 importCsv。把本席写成「仍 422」= FAIL',
  );

  await pickAntOption(page, dialog, new RegExp(siteCode));
  const skip = page.getByTestId('import-skip-errors').or(
    page.getByRole('checkbox', { name: new RegExp(SKIP_ERRORS_LABEL) }),
  );
  if (!(await skip.count())) {
    throw new Error('向导未见「跳过错误行」。钩子缺失即红，不得 skip');
  }
  if (!(await skip.first().isChecked().catch(() => false))) {
    await skip.first().click();
  }
  if (!(await skip.first().isChecked().catch(() => false))) {
    throw new Error('Must 4 必须勾选「跳过错误行」。不得写成整批 422 / 仍 422');
  }

  const fileInput = page.locator('input[type=file]').first();
  if (!(await fileInput.count())) {
    throw new Error('向导未见 file input。禁止改走 importCsv，不得 skip');
  }
  await fileInput.setInputFiles(csv);

  const auto = page.getByRole('checkbox', { name: /导入后自动重算/ });
  if (await auto.isChecked().catch(() => false)) {
    await auto.uncheck();
  }

  await page.getByRole('button', { name: /开始导入/ }).click();
  const started = Date.now();
  while (!importResponse && Date.now() - started < 120000) {
    await page.waitForTimeout(200);
  }
  if (!importResponse) {
    throw new Error(
      '向导点「开始导入」后未见 POST /orders/import。结果步未见成功/失败行数 = FAIL。禁止改走 importCsv。把本席写成「仍 422」= FAIL',
    );
  }

  await requireHooks(
    page,
    MUST4_RESULT_HOOKS,
    '结果步须见 import-success-rows / import-failed-rows / import-not-payroll。钩子缺失即红，不得 skip。把本席写成「仍 422」= FAIL',
  );
  const resultText = await page.getByTestId('ops-import-skip-errors-not-all-success').or(dialog).innerText();
  const failedText = await page.getByTestId('import-failed-rows').innerText();
  const successText = await page.getByTestId('import-success-rows').innerText();
  const failedRows = Number((failedText.match(/\d+/) || [''])[0]);
  const successRows = Number((successText.match(/\d+/) || [''])[0]);
  if (!Number.isFinite(failedRows) || failedRows < 1) {
    throw new Error(
      `夹具为合法行 + 1 行必失败，结果步须 failed_rows ≥ 1。实际「${failedText}」。把本席写成「仍 422」= FAIL`,
    );
  }
  assertHalfSuccessVisible(`${resultText}\n${failedText}\n${successText}`, {
    successRows,
    failedRows,
    where: '结果步',
  });
  const notPayroll = await page.getByTestId('import-not-payroll').innerText();
  if (!IMPORT_NOT_PAYROLL_COPY.test(notPayroll)) {
    throw new Error(`Cycle 1「导入完成 ≠ 已出账」仍要出现，不能拿它代替「有 N 行未入库」。实际：${notPayroll}`);
  }

  const next = page.getByRole('button', { name: /下一步/ });
  if (await next.count()) {
    await next.first().click();
  } else {
    throw new Error(
      '完成步不可达。完成步只剩「导入流程已完成」且失败行数消失 = FAIL。不得用去算薪页藏起失败行数',
    );
  }
  await requireHooks(
    page,
    MUST4_COMPLETE_HOOKS,
    '完成步须同时看得见成功行数、失败行数 N，以及错误表/下载完整错误报告。失败行数消失 = FAIL，不得 skip',
  );
  const completeText = await page.getByTestId('ops-import-skip-errors-not-all-success').or(dialog).innerText();
  const completeFailed = await page.getByTestId('import-failed-rows').innerText();
  const completeSuccess = await page.getByTestId('import-success-rows').innerText();
  assertHalfSuccessVisible(`${completeText}\n${completeFailed}\n${completeSuccess}`, {
    successRows,
    failedRows,
    where: '完成步',
  });
  const report = page.getByTestId('import-error-report');
  if (!(await report.first().isVisible().catch(() => false))) {
    throw new Error('完成步错误表或「下载完整错误报告」须仍可到达，不得 skip');
  }

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-import-skip-errors-not-all-success');
}
