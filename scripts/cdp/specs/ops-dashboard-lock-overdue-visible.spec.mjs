/** CDP: ops-dashboard-lock-overdue-visible — #27 倒计时含过期未锁；查看全部 lock_due=1 */
import {
  LOCK_OVERDUE_COPY,
  LOCK_REMAINING_COPY,
  LOCK_TITLE,
  duePeriodVisible,
  fetchDashboardSummary,
  queryOf,
  requireTestId,
  siteMonth,
  waitPath,
} from '../cycle4-lib.mjs';

export const name = 'ops-dashboard-lock-overdue-visible';

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function shiftDay(iso, days) {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();
  const today = todayIso();

  const summary = await fetchDashboardSummary(config.apiUrl, token, { siteId, month });
  const live = (summary?.attention || []).find((row) => row.key === 'due_periods');
  if (live?.title && live.title !== LOCK_TITLE) {
    throw new Error(`标题须为「${LOCK_TITLE}」。实际 ${live.title}`);
  }

  const OVERDUE_ID = 92001;
  const NEAR_ID = 92002;
  const FAR_ID = 92003;
  await page.route('**/api/v1/rider-salary/dashboard/summary**', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.continue();
      return;
    }
    const res = await route.fetch();
    const json = await res.json();
    const data = json?.data || {};
    const attention = Array.isArray(data.attention) ? [...data.attention] : [];
    const due = {
      key: 'due_periods',
      title: LOCK_TITLE,
      count: 3,
      link: `/rider-salary/period?status=open`,
      items: [
        {
          period_id: OVERDUE_ID,
          end_date: shiftDay(today, -5),
          days_left: -5,
          status: 'open',
          range: `${shiftDay(today, -20)} ~ ${shiftDay(today, -5)}`,
          link: `/rider-salary/period?id=${OVERDUE_ID}`,
        },
        {
          period_id: NEAR_ID,
          end_date: shiftDay(today, 2),
          days_left: 2,
          status: 'reopened',
          range: `${month}-01 ~ ${shiftDay(today, 2)}`,
          link: `/rider-salary/period?id=${NEAR_ID}`,
        },
        {
          period_id: FAR_ID,
          end_date: shiftDay(today, 10),
          days_left: 10,
          status: 'open',
          range: `${shiftDay(today, 1)} ~ ${shiftDay(today, 10)}`,
          link: `/rider-salary/period?id=${FAR_ID}`,
        },
      ],
    };
    const idx = attention.findIndex((row) => row.key === 'due_periods');
    if (idx >= 0) attention[idx] = due;
    else attention.push(due);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...json, data: { ...data, attention } }),
    });
  });

  await page.goto(
    `${config.adminUrl}/rider-salary/dashboard?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );

  await requireTestId(page, 'ops-dashboard-lock-overdue-visible', '未见 #27 块 ops-dashboard-lock-overdue-visible');
  await requireTestId(page, 'dashboard-lock-title', '未见 dashboard-lock-title');
  const titleText = await page.getByTestId('dashboard-lock-title').innerText();
  if (titleText.trim() !== LOCK_TITLE) {
    throw new Error(`dashboard-lock-title 须为「${LOCK_TITLE}」。实际 ${titleText}`);
  }
  // a-collapse 默认折叠；过期/剩余行与查看全部在 panel 体内
  await page.getByTestId('ops-dashboard-lock-overdue-visible').first().click();
  await requireTestId(page, 'dashboard-lock-overdue', '未见过期行 dashboard-lock-overdue');
  const overdueText = await page.getByTestId('dashboard-lock-overdue').first().innerText();
  if (!LOCK_OVERDUE_COPY.test(overdueText)) {
    throw new Error(`过期行须写「已过期未锁 N 天」：${overdueText}`);
  }
  await requireTestId(page, 'dashboard-lock-remaining', '未见未到期 dashboard-lock-remaining');
  const remainText = await page.getByTestId('dashboard-lock-remaining').first().innerText();
  if (!LOCK_REMAINING_COPY.test(remainText)) {
    throw new Error(`未到期须写「剩余 N 天」：${remainText}`);
  }

  const body = await page.locator('body').innerText();
  if (body.includes(String(FAR_ID))) {
    throw new Error('远周期 +10 天不必占待办（#27 前端按 days_left≤3 过滤）');
  }
  if (body.includes('仍要锁')) throw new Error('不恢复「仍要锁」');
  if (!duePeriodVisible(shiftDay(today, -5), today) || duePeriodVisible(shiftDay(today, 10), today)) {
    throw new Error('倒计时窗口合同：过期可见、+10 不可见');
  }

  await page.getByTestId('dashboard-lock-overdue').first().click();
  const rowUrl = await waitPath(page, /\/rider-salary\/period/);
  if (!rowUrl.includes(String(OVERDUE_ID)) && !queryOf(rowUrl).get('id') && !queryOf(rowUrl).get('period_id')) {
    throw new Error(`点行须带 period_id/id。实际 ${rowUrl}`);
  }

  await page.goto(
    `${config.adminUrl}/rider-salary/dashboard?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  await requireTestId(page, 'ops-dashboard-lock-overdue-visible', '返回工作台未见锁账倒计时块');
  await page.getByTestId('ops-dashboard-lock-overdue-visible').first().click();
  await requireTestId(page, 'dashboard-lock-view-all', '未见 dashboard-lock-view-all');
  await page.getByTestId('dashboard-lock-view-all').first().click();
  const allUrl = await waitPath(page, /\/rider-salary\/period/);
  const q = queryOf(allUrl);
  if (q.get('lock_due') !== '1' && q.get('lock_due') !== 'true') {
    throw new Error(`查看全部须 /period?lock_due=1。实际 ${allUrl}`);
  }
  if (q.get('status') === 'open' && !q.get('month') && q.get('lock_due') !== '1') {
    throw new Error(`不得只切无月份的 status=open 第一页。实际 ${allUrl}`);
  }
  await requireTestId(page, 'period-lock-due-scope', '落地须见 period-lock-due-scope');

  helpers.assertNoPaymentTaxCopy(body);
  await helpers.shot(page, 'cdp-ops-dashboard-lock-overdue-visible');
}
