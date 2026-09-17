/** CDP: ops-import-wizard-lighthouse — 向导上传灯塔样例必须走通；API 绿 ≠ 交付 */
import fs from 'node:fs';

import {
  FILE_REQUIRED_422,
  IMPORT_NOT_PAYROLL_COPY,
  LIGHTHOUSE_XLSX_NAME,
  MUST1_RESULT_HOOKS,
  MUST1_WIZARD_HOOKS,
  assertImportUsedRealFile,
  assertLockedGoldUnchanged,
  lighthouseXlsxPath,
  openImportWizard,
  pickAntOption,
  requireHooks,
  siteMonth,
  waitPath,
} from '../cycle13-lib.mjs';

export const name = 'ops-import-wizard-lighthouse';

export async function run({ page, helpers, config }) {
  assertLockedGoldUnchanged();
  if (typeof globalThis.importCsv === 'function') {
    throw new Error('本席禁止走 importCsv。API 绿冒充向导交付 = FAIL');
  }
  const xlsx = lighthouseXlsxPath();
  if (!fs.existsSync(xlsx) || !xlsx.endsWith(LIGHTHOUSE_XLSX_NAME)) {
    throw new Error(`Must 1 必须用灯塔样例 ${LIGHTHOUSE_XLSX_NAME}，不得 skip、不得改 CSV`);
  }

  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const { siteCode } = siteMonth();

  let importResponse = null;
  page.on('response', async (res) => {
    if (res.request().method() === 'POST' && /\/orders\/import/.test(res.url())) {
      importResponse = res;
      try {
        res._cycle13BodyText = await res.text();
      } catch {
        res._cycle13BodyText = '';
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
    MUST1_WIZARD_HOOKS,
    '未见 ops-import-wizard-lighthouse / import-wizard-file。向导钩子缺失即红，不得 skip。用 API importCsv 绿 = FAIL',
  );

  await pickAntOption(page, dialog, new RegExp(siteCode));
  const fileInput = page.getByTestId('import-wizard-file').locator('input[type=file]').first();
  const fallbackInput = page.locator('input[type=file]').first();
  const input = (await fileInput.count()) ? fileInput : fallbackInput;
  if (!(await input.count())) {
    throw new Error('向导未见 file input。钩子缺失即红，不得改走 API');
  }
  await input.setInputFiles(xlsx);

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
      '向导点「开始导入」后未见 POST /orders/import。请求未带文件或未发出 = FAIL。禁止改走 importCsv',
    );
  }
  assertImportUsedRealFile(importResponse.request(), importResponse);
  const failBody = importResponse._cycle13BodyText || '';
  if (FILE_REQUIRED_422.test(failBody)) {
    throw new Error(`仍 422「file 字段为必填项」= FAIL。${failBody.slice(0, 300)}`);
  }

  await requireHooks(
    page,
    MUST1_RESULT_HOOKS,
    '结果步须见 import-not-payroll / import-goto-calculate（旧钩子仍须出现）。API 绿不够，不得 skip',
  );
  const result = page.getByTestId('import-not-payroll').first();
  const copy = await result.innerText();
  if (!IMPORT_NOT_PAYROLL_COPY.test(copy)) {
    throw new Error(`结果步须写明「导入完成 ≠ 已出账」：${copy.slice(0, 200)}`);
  }
  await helpers.shot(page, 'cdp-ops-import-wizard-lighthouse-result');
  await page.getByTestId('import-goto-calculate').first().click();
  await waitPath(page, /\/rider-salary\/period\/\d+\/calculate/, 30000);

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-import-wizard-lighthouse');
}
