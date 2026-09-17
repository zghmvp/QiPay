/** CDP: cdp-admin-calc-success-four-numbers — 算薪页成功行四数；点进已分层条；失败行姓名 */
import { siteLevelOpenPeriod, siteMonth } from '../cycle1-lib.mjs';
import { LAYER_TITLES, RECON_COPY } from '../cycle2-lib.mjs';

export const name = 'cdp-admin-calc-success-four-numbers';

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();
  const period = await siteLevelOpenPeriod({ apiUrl: config.apiUrl, token, siteId, month });
  if (!period?.id) throw new Error('本站无开放周期');

  await page.goto(`${config.adminUrl}/rider-salary/period/${period.id}/calculate`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  const table = page.getByTestId('period-calc-payrolls');
  await table.waitFor({ state: 'visible', timeout: 20000 });
  const head = await table.innerText();
  if (!head.includes('代扣') || !/预支/.test(head)) {
    throw new Error(`算薪页成功表须有代扣与预支抵扣列（可为 0）：${head.slice(0, 200)}`);
  }
  if (!head.includes('应发') || !head.includes('实发')) {
    throw new Error('成功表须保留应发/实发列');
  }

  const failed = page.getByTestId('period-calc-failed');
  if (await failed.isVisible().catch(() => false)) {
    const failText = await failed.innerText();
    if (!/姓名/.test(failText) && /骑手 #\d+/.test(failText)) {
      throw new Error('失败行可见姓名（预检 blocker / failed[] 对齐），不得只显示骑手 #id');
    }
    if (/工号\s+\S+/.test(failText) && !/[\u4e00-\u9fff]{2,}/.test(failText.replace(/工号/g, ''))) {
      throw new Error(`失败行须补姓名，禁止只重复工号：${failText.slice(0, 200)}`);
    }
  }

  const detailBtn = page.getByTestId('period-calc-payroll-detail').first();
  await detailBtn.waitFor({ state: 'visible', timeout: 15000 });
  await detailBtn.click();
  await page.waitForURL(/\/rider-salary\/payroll\/\d+/, { timeout: 30000 });

  const layers = page.getByTestId('payroll-layers');
  await layers.waitFor({ state: 'visible', timeout: 20000 });
  const recon = page.getByTestId('payroll-reconciliation');
  await recon.waitFor({ state: 'visible', timeout: 10000 });
  const reconText = await recon.innerText();
  const body = await layers.innerText();
  if (!RECON_COPY.test(reconText)) {
    const missing = LAYER_TITLES.filter((title) => !body.includes(title));
    throw new Error(
      `从算薪页点明细须落到已分层的 /payroll/:id。payroll-reconciliation=${reconText.slice(0, 80)} 缺分区：${missing.join('、')}`,
    );
  }
  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-admin-calc-success-four-numbers');
}
