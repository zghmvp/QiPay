/** CDP: cdp-admin-payslip-layers — /payroll/:id 应发−代扣−预支勾稽分层 */
import {
  LAYER_TITLES,
  RECON_COPY,
  assertReconNumbers,
  getPayrollDetail,
  parseMoney,
  pickPayrollWithMoney,
  siteMonth,
} from '../cycle2-lib.mjs';

export const name = 'cdp-admin-payslip-layers';

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId } = siteMonth();
  const row = await pickPayrollWithMoney({ apiUrl: config.apiUrl, token, siteId });
  const detail = await getPayrollDetail(config.apiUrl, token, row.id);
  assertReconNumbers({
    gross: detail.gross,
    deduction: detail.deduction_total,
    advance: detail.advance_deduction,
    net: detail.net,
  });

  const breakdown = detail.subject_breakdown || [];
  const mixed = new Map();
  for (const item of breakdown) {
    const key = String(item.subject_id);
    const flags = mixed.get(key) || new Set();
    flags.add(Boolean(item.include_in_gross));
    mixed.set(key, flags);
  }
  const mixedIds = [...mixed.entries()].filter(([, flags]) => flags.size > 1).map(([id]) => id);

  await page.goto(`${config.adminUrl}/rider-salary/payroll/${row.id}`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  const body = await page.locator('body').innerText();
  helpers.assertNoPaymentTaxCopy(body);

  const layers = page.getByTestId('payroll-layers');
  try {
    await layers.waitFor({ state: 'visible', timeout: 20000 });
  } catch {
    throw new Error('明细页须有 payroll-layers（应发 / 代扣 / 预支抵扣 / 实发）。四数并排不算绿');
  }
  const layersText = await layers.innerText();
  const missingTitles = LAYER_TITLES.filter((title) => !layersText.includes(title));
  if (missingTitles.length) {
    throw new Error(`payroll-layers 缺分区标题：${missingTitles.join('、')}`);
  }

  const recon = page.getByTestId('payroll-reconciliation');
  try {
    await recon.waitFor({ state: 'visible', timeout: 10000 });
  } catch {
    throw new Error('须有 payroll-reconciliation 勾稽句：应发 − 代扣 − 预支抵扣 = 实发');
  }
  const reconText = await recon.innerText();
  if (!RECON_COPY.test(reconText)) {
    throw new Error(`payroll-reconciliation 须可断言勾稽句：${reconText}`);
  }

  const nums = {
    gross: parseMoney(detail.gross),
    deduction: parseMoney(detail.deduction_total),
    advance: parseMoney(detail.advance_deduction),
    net: parseMoney(detail.net),
  };
  assertReconNumbers(nums);

  if (mixedIds.length) {
    const rows = layers.locator('tr');
    const count = await rows.count();
    if (count < 2) {
      throw new Error(`混合 include_in_gross 科目 ${mixedIds.join(',')} 须拆行，禁止取主`);
    }
  }

  if (/个税|社保|已打款/.test(layersText)) {
    throw new Error('分层不得新增个税/社保/打款行');
  }
  await helpers.shot(page, 'cdp-admin-payslip-layers');
}
