/** CDP: ops-calc-success-vs-existing — ② 本次成功表 vs ③ 已有薪资，禁止只用 ③ 代替 */
import { siteLevelOpenPeriod, siteMonth } from '../cycle1-lib.mjs';
import {
  EXISTING_PAYROLL_COPY,
  RUN_SUCCESS_COPY,
} from '../cycle3-lib.mjs';

export const name = 'ops-calc-success-vs-existing';

const OLD_JOB = 'FIX_C17_R1';
const NEW_JOB = 'FIX_C03_R1';

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();
  const period = await siteLevelOpenPeriod({ apiUrl: config.apiUrl, token, siteId, month });
  if (!period?.id) throw new Error('本站无开放周期');

  let ranThisCalc = false;
  await page.route('**/api/v1/rider-salary/periods/*/calculate', async (route) => {
    if (route.request().method() !== 'POST') {
      await route.continue();
      return;
    }
    ranThisCalc = true;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 200,
        msg: '成功',
        data: {
          calculated: 1,
          queued: false,
          calculated_rider_ids: [41],
          failed_count: 1,
          failed: [
            {
              rider_id: 9,
              job_no: OLD_JOB,
              rider_name: '换绑夹具骑手',
              errors: ['无生效方案'],
            },
          ],
        },
      }),
    });
  });

  await page.route(`**/api/v1/rider-salary/periods/${period.id}`, async (route) => {
    if (route.request().method() !== 'GET') {
      await route.continue();
      return;
    }
    const res = await route.fetch();
    const json = await res.json();
    const data = json?.data || {};
    const payrolls = Array.isArray(data.payrolls) ? [...data.payrolls] : [];
    if (!payrolls.some((row) => row.job_no === OLD_JOB || /换绑/.test(row.rider_name || ''))) {
      payrolls.push({
        id: 90001,
        rider_id: 9,
        job_no: OLD_JOB,
        rider_name: '换绑夹具骑手',
        order_count: 10,
        gross: '100.00',
        deduction_total: '0.00',
        advance_deduction: '0.00',
        net: '100.00',
      });
    }
    if (!payrolls.some((row) => row.job_no === NEW_JOB || row.rider_id === 41)) {
      payrolls.push({
        id: 91001,
        rider_id: 41,
        job_no: NEW_JOB,
        rider_name: '金标C03骑手',
        order_count: 650,
        gross: '8200.00',
        deduction_total: '0.00',
        advance_deduction: '0.00',
        net: '8200.00',
      });
    }
    data.payrolls = payrolls;
    data.last_calc_success_ids = ranThisCalc ? [41] : [];
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...json, data }),
    });
  });

  await page.goto(`${config.adminUrl}/rider-salary/period/${period.id}/calculate`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });

  const start = page.getByTestId('period-calc-start');
  if (await start.isEnabled().catch(() => false)) {
    await start.click();
  } else {
    await page.evaluate(() => {
      document.querySelector('[data-testid="period-calc-start"]')?.click();
    });
  }

  const success = page.getByTestId('period-calc-run-success');
  try {
    await success.waitFor({ state: 'visible', timeout: 20000 });
  } catch {
    throw new Error(
      '须有 ②「本次成功」表 period-calc-run-success。禁止只用 ③ Tag period-calc-payroll-this-run-tag 代替成功表',
    );
  }
  const tagOnly = page.getByTestId('period-calc-payroll-this-run-tag');
  if ((await tagOnly.count()) && !(await success.isVisible().catch(() => false))) {
    throw new Error('③ Tag「本轮新出」不够绿，必须另有 ② period-calc-run-success');
  }
  const successText = await success.innerText();
  if (!RUN_SUCCESS_COPY.test(successText) && !successText.includes('本次成功')) {
    throw new Error(`period-calc-run-success 须标明本次成功：${successText.slice(0, 200)}`);
  }
  if (
    !successText.includes(NEW_JOB) &&
    !successText.includes('金标C03') &&
    !/本次成功（[1-9]/.test(successText)
  ) {
    throw new Error(`② 本次成功须含本轮算出的人（${NEW_JOB}），不得空表冒充完成`);
  }
  if (successText.includes(OLD_JOB) && !successText.includes('失败')) {
    throw new Error(`② 本次成功不得把旧单 ${OLD_JOB} 当成刚算出`);
  }
  if (!successText.includes('代扣') || !/预支/.test(successText) || !successText.includes('应发')) {
    throw new Error(`② 成功表须沿用 Cycle 2 四数（应发/代扣/预支抵扣/实发）：${successText.slice(0, 200)}`);
  }

  const failed = page.getByTestId('period-calc-failed');
  await failed.waitFor({ state: 'visible', timeout: 10000 });
  const failText = await failed.innerText();
  if (!failText.includes(OLD_JOB) && !/换绑/.test(failText)) {
    throw new Error('失败仍须在 ②，本轮夹具失败骑手须可见');
  }

  const existing = page.getByTestId('period-calc-payrolls');
  await existing.waitFor({ state: 'visible', timeout: 15000 });
  const existingText = await existing.innerText();
  if (!EXISTING_PAYROLL_COPY.test(existingText) && !existingText.includes('已有')) {
    const title = await page.locator('[data-testid="period-calc-payrolls"]').evaluate((el) => {
      const card = el.closest('.ant-card');
      return card ? card.innerText.slice(0, 80) : el.innerText.slice(0, 80);
    });
    if (!EXISTING_PAYROLL_COPY.test(title)) {
      throw new Error(`③ 标题须为周期内已有薪资：${title}`);
    }
  }
  if (!existingText.includes(OLD_JOB) && !/换绑/.test(existingText)) {
    throw new Error(`③ 已有薪资须能见到旧单 ${OLD_JOB}`);
  }

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-calc-success-vs-existing');
}
