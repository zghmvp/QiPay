/** CDP: cdp-admin-subject-filter-name — 科目筛用科目名，不用「科目 ID n」独占 */
import { apiFetch, siteMonth } from '../cycle1-lib.mjs';

export const name = 'cdp-admin-subject-filter-name';

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId } = siteMonth();

  const list = await apiFetch(
    config.apiUrl,
    token,
    'GET',
    `/api/v1/rider-salary/payrolls?site_id=${siteId}&page=1&size=20`,
  );
  const items = list.json?.data?.items || [];
  if (!items.length) throw new Error('本站无薪资结果，无法测科目筛标签');

  let subject = null;
  let payrollId = null;
  for (const row of items) {
    const detail = await apiFetch(
      config.apiUrl,
      token,
      'GET',
      `/api/v1/rider-salary/payrolls/${row.id}`,
    );
    const breakdown = detail.json?.data?.subject_breakdown || [];
    const hit = breakdown.find((b) => b.subject_id && b.subject_name);
    if (hit) {
      subject = hit;
      payrollId = row.id;
      break;
    }
    const grouped = detail.json?.data?.details || {};
    const line = Object.values(grouped).flat().find((d) => d.subject_id && d.subject_name);
    if (line) {
      subject = line;
      payrollId = row.id;
      break;
    }
  }
  if (!subject || !payrollId) {
    throw new Error('薪资明细没有带名称的科目');
  }

  await page.goto(
    `${config.adminUrl}/rider-salary/payroll/${payrollId}?tab=details&subject_id=${subject.subject_id}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  const chip = page.getByTestId('payroll-subject-filter');
  await chip.waitFor({ state: 'visible', timeout: 20000 });
  const text = await chip.innerText();
  if (new RegExp(`科目 ID\\s*${subject.subject_id}`).test(text) && !text.includes(subject.subject_name)) {
    throw new Error(`科目筛仍是「科目 ID ${subject.subject_id}」，须用科目名「${subject.subject_name}」`);
  }
  if (!text.includes(subject.subject_name) && !text.includes('已筛选')) {
    throw new Error(`payroll-subject-filter 未见科目名：${text}`);
  }
  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-admin-subject-filter-name');
}
