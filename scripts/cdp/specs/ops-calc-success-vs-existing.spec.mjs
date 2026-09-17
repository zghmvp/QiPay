/** CDP: ops-calc-success-vs-existing — ② 本次成功表 vs ③ 已有薪资；须绑 thisRunPayrolls */
import { apiFetch, siteLevelOpenPeriod, siteMonth } from '../cycle1-lib.mjs';
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

  const ridersRes = await apiFetch(
    config.apiUrl,
    token,
    'GET',
    `/api/v1/rider-salary/riders?page=1&size=50&site_id=${siteId}`,
  );
  const riders = ridersRes.json?.data?.items || [];
  const oldRider = riders.find((r) => r.job_no === OLD_JOB);
  const newRider = riders.find((r) => r.job_no === NEW_JOB);
  if (!oldRider?.id || !newRider?.id) {
    throw new Error(`缺夹具骑手 ${OLD_JOB}/${NEW_JOB}，请先灌种`);
  }
  const oldId = Number(oldRider.id);
  const newId = Number(newRider.id);

  // 正式算出 NEW（填充 last_calc_success_ids + ② thisRunPayrolls）
  const calc = await apiFetch(
    config.apiUrl,
    token,
    'POST',
    `/api/v1/rider-salary/periods/${period.id}/calculate`,
    { rider_ids: [newId] },
  );
  if (!calc.res.ok) {
    throw new Error(
      `正式 calculate ${NEW_JOB} 失败 HTTP ${calc.res.status}：${JSON.stringify(calc.json).slice(0, 300)}`,
    );
  }

  // GET 周期时注入旧单到 ③，不改 last_calc_success_ids（保留后端本轮成功 id）
  const basePeriod = await apiFetch(
    config.apiUrl,
    token,
    'GET',
    `/api/v1/rider-salary/periods/${period.id}`,
  );
  const baseData = structuredClone(basePeriod.json?.data || { id: period.id, payrolls: [] });

  await page.route(`**/api/v1/rider-salary/periods/${period.id}**`, async (route) => {
    const url = route.request().url();
    if (
      route.request().method() !== 'GET' ||
      /\/(calculate|calc-precheck|export|calc-riders|lock)(?:\?|$)/.test(url)
    ) {
      await route.continue();
      return;
    }
    const data = structuredClone(baseData);
    const payrolls = Array.isArray(data.payrolls) ? [...data.payrolls] : [];
    if (!payrolls.some((row) => Number(row.rider_id) === oldId || row.job_no === OLD_JOB)) {
      payrolls.push({
        id: 90001,
        rider_id: oldId,
        job_no: OLD_JOB,
        rider_name: oldRider.name || '换绑夹具骑手',
        order_count: 10,
        gross: '100.00',
        deduction_total: '0.00',
        advance_deduction: '0.00',
        net: '100.00',
      });
    }
    data.payrolls = payrolls;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code: 200, msg: '成功', data }),
    });
  });

  // 失败行：拦截一次 calculate 只返回失败旧骑手（开始算薪后再点会覆盖；改为直接展示已有 lastResult 难）
  // 改为：页加载后若 ② 已有成功行，再点开始并 mock 一次带失败的 calculate
  let failInjected = false;
  await page.route('**/api/v1/rider-salary/periods/*/calculate', async (route) => {
    if (route.request().method() !== 'POST') {
      await route.continue();
      return;
    }
    failInjected = true;
    const successIds = Array.isArray(baseData.last_calc_success_ids)
      ? baseData.last_calc_success_ids
      : [newId];
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 200,
        msg: '成功',
        data: {
          calculated: successIds.length,
          queued: false,
          calculated_rider_ids: successIds,
          failed_count: 1,
          failed: [
            {
              rider_id: oldId,
              job_no: OLD_JOB,
              rider_name: oldRider.name || '换绑夹具骑手',
              errors: ['无生效方案'],
            },
          ],
        },
      }),
    });
  });

  await page.goto(`${config.adminUrl}/rider-salary/period/${period.id}/calculate`, {
    waitUntil: 'domcontentloaded',
    timeout: 60000,
  });
  await page.getByTestId('period-calc-run-success').waitFor({ state: 'visible', timeout: 30000 });

  // 刷新以拉取 last_calc_success_ids → thisRunPayrolls
  const refresh = page.getByTestId('period-calc-refresh');
  if (await refresh.count()) {
    await refresh.click();
    await page.waitForTimeout(800);
  }

  // 再点开始注入失败行（mock calculate）
  const start = page.getByTestId('period-calc-start');
  await start.waitFor({ state: 'visible', timeout: 15000 });
  if (!(await start.isDisabled().catch(() => true))) {
    await start.click();
  } else {
    await start.click({ force: true });
  }
  await page.waitForTimeout(1000);

  const success = page.getByTestId('period-calc-run-success');
  const successText = await success.innerText();
  if (!RUN_SUCCESS_COPY.test(successText) && !successText.includes('本次成功')) {
    throw new Error(`period-calc-run-success 须标明本次成功：${successText.slice(0, 200)}`);
  }
  const empty = page.getByTestId('period-calc-run-success-empty');
  if (await empty.isVisible().catch(() => false)) {
    throw new Error(
      `② 本次成功表不得为空（须 :data-source="thisRunPayrolls"，#24 bind）。文案=${successText.slice(0, 240)}`,
    );
  }
  const table = page.getByTestId('period-calc-run-success-table');
  if (!(await table.isVisible().catch(() => false))) {
    throw new Error('② 须有 period-calc-run-success-table（thisRunPayrolls 绑定）');
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
    if (!failInjected) {
      throw new Error('失败仍须在 ②；本轮未能注入失败行');
    }
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
