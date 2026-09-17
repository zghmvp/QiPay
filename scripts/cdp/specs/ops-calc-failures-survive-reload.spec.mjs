/** CDP: ops-calc-failures-survive-reload — 失败可 F5 + 抽屉去算薪 */
export const name = 'ops-calc-failures-survive-reload';

const FIX_JOB_NO = 'FIX_C17_R1';

async function authHeaders(token) {
  return { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
}

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const headers = await authHeaders(admin.access_token);
  const siteId = process.env.CDP_SITE_ID || '13';
  const month = process.env.CDP_MONTH || '2026-09';

  const listRes = await fetch(
    `${config.apiUrl}/api/v1/rider-salary/periods?site_id=${siteId}&month=${month}&page=1&size=50`,
    { headers },
  );
  if (!listRes.ok) throw new Error(`周期列表失败 ${listRes.status}`);
  const listJson = await listRes.json();
  const period = (listJson?.data?.items || [])[0];
  if (!period?.id) {
    throw new Error('未找到周期。请先生成 2026-09 福民周期');
  }

  const calcRes = await fetch(
    `${config.apiUrl}/api/v1/rider-salary/periods/${period.id}/calculate`,
    { method: 'POST', headers, body: '{}' },
  );
  const calcJson = await calcRes.json();
  const failed = calcJson?.data?.failed || [];
  if (!failed.length) {
    throw new Error(
      `夹具周期算薪未产生 failed[]（期望含 ${FIX_JOB_NO} 无方案）。body=${JSON.stringify(calcJson).slice(0, 400)}`,
    );
  }
  const detailRes = await fetch(
    `${config.apiUrl}/api/v1/rider-salary/periods/${period.id}`,
    { headers },
  );
  const detail = (await detailRes.json())?.data;
  const persisted = detail?.last_calc_failures || [];
  if (!persisted.length) {
    throw new Error('GET 周期详情缺少 last_calc_failures，失败未落库');
  }
  const text = JSON.stringify(persisted);
  if (!text.includes('无生效方案') && !text.includes(FIX_JOB_NO) && !/工号/.test(text)) {
    throw new Error(`落库失败清单缺少中文/工号：${text.slice(0, 300)}`);
  }

  await page.goto(
    `${config.adminUrl}/rider-salary/period/${period.id}/calculate`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  const failedBox = page.getByTestId('period-calc-failed');
  await failedBox.waitFor({ state: 'visible', timeout: 20000 });
  const failText = await failedBox.innerText();
  if (!/无生效方案|失败/.test(failText)) {
    throw new Error(`算薪页失败区缺少中文错误：${failText.slice(0, 200)}`);
  }
  await page.reload({ waitUntil: 'networkidle' });
  await page.getByTestId('period-calc-failed').waitFor({ state: 'visible', timeout: 20000 });
  const after = await page.getByTestId('period-calc-failed').innerText();
  if (!/无生效方案|失败/.test(after)) {
    throw new Error(`F5 后失败区消失：${after.slice(0, 200)}`);
  }

  await page.goto(
    `${config.adminUrl}/rider-salary/period?id=${period.id}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  const goCalc = page.getByTestId('period-detail-go-calculate');
  await goCalc.waitFor({ state: 'visible', timeout: 20000 });
  await goCalc.click();
  await page.waitForURL(new RegExp(`/rider-salary/period/${period.id}/calculate`), {
    timeout: 20000,
  });
  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-calc-failures-survive-reload');
}
