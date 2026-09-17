/** CDP: ops-payroll-list-period-picker — /payroll 周期为本站选择器，深链预中 */
import { apiFetch, siteLevelOpenPeriod, siteMonth } from '../cycle1-lib.mjs';

export const name = 'ops-payroll-list-period-picker';

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();
  const target = await siteLevelOpenPeriod({
    apiUrl: config.apiUrl,
    token,
    siteId,
    month,
  });
  if (!target?.id) throw new Error('本站无周期，无法测薪资结果周期选择器');

  await page.goto(
    `${config.adminUrl}/rider-salary/payroll?site_id=${siteId}&period_id=${target.id}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );

  const picker = page.getByTestId('payroll-period-picker');
  await picker.waitFor({ state: 'visible', timeout: 20000 });
  const pkInput = page.locator('.ant-form-item').filter({ hasText: /^周期$/ }).locator('.ant-input-number, input[placeholder*="周期 ID"]');
  if ((await pkInput.count()) > 0) {
    throw new Error('薪资结果周期筛仍是填主键 InputNumber');
  }
  const selected = await picker.innerText();
  if (
    !String(selected).includes(String(target.id)) &&
    !/\d{4}-\d{2}-\d{2}/.test(selected)
  ) {
    throw new Error(`深链 period_id=${target.id} 未预中。选择器：${selected}`);
  }

  await picker.click();
  const options = page.locator('.ant-select-dropdown:visible .ant-select-item-option');
  await options.first().waitFor({ state: 'visible', timeout: 15000 });
  const labels = await options.allInnerTexts();
  const sites = await apiFetch(config.apiUrl, token, 'GET', '/api/v1/rider-salary/sites/all');
  const other = (sites.json?.data || []).find((s) => String(s.id) !== String(siteId));
  if (other?.id) {
    const otherPeriods = await apiFetch(
      config.apiUrl,
      token,
      'GET',
      `/api/v1/rider-salary/periods?site_id=${other.id}&page=1&size=20`,
    );
    const foreign = (otherPeriods.json?.data?.items || []).map((row) => String(row.id));
    const leaked = labels.filter((label) =>
      foreign.some((id) => new RegExp(`(^|\\D)${id}(\\D|$)`).test(label) && !label.includes(String(target.start_date || ''))),
    );
    if (leaked.length) {
      throw new Error(`周期选择器出现他站周期：${leaked.slice(0, 3).join('、')}`);
    }
  }

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-payroll-list-period-picker');
}
