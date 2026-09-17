/** CDP: ops-dashboard-insight-card-scope — #27 洞察卡/空态/Top 深链带本站本月；在职列表消费 status */
import {
  EMPTY_IMPORT_COPY,
  INSIGHT_CARD_IDS,
  assertLockedGoldUnchanged,
  assertSiteMonthInUrl,
  fetchRiders,
  queryOf,
  requireTestId,
  siteMonth,
  waitPath,
} from '../cycle4-lib.mjs';

export const name = 'ops-dashboard-insight-card-scope';

export async function run({ page, helpers, config }) {
  assertLockedGoldUnchanged();
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();

  const riderReqs = [];
  page.on('request', (req) => {
    if (req.method() === 'GET' && /\/api\/v1\/rider-salary\/riders\?/.test(req.url())) {
      riderReqs.push(req.url());
    }
  });

  await page.route('**/api/v1/rider-salary/dashboard/summary**', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.continue();
      return;
    }
    const res = await route.fetch();
    const json = await res.json();
    const data = json?.data || {};
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...json,
        data: {
          ...data,
          cards: {
            on_job_riders: 4,
            month_order_count: 12,
            month_valid_order_count: 10,
            estimated_gross: '8200.00',
            pending_advances: 1,
            to_pay_advances: 1,
          },
          top_riders: {
            top: [{ rider_id: 41, job_no: 'FIX_C03_R1', name: '金标C03', order_count: 20 }],
            bottom: [{ rider_id: 9, job_no: 'FIX_C17_R1', name: '换绑夹具', order_count: 1 }],
          },
        },
      }),
    });
  });

  await page.goto(
    `${config.adminUrl}/rider-salary/dashboard?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  await requireTestId(page, 'ops-dashboard-insight-card-scope', '未见根钩子 ops-dashboard-insight-card-scope');

  const cards = [
    {
      testId: INSIGHT_CARD_IDS.onJob,
      path: /\/rider-salary\/rider/,
      check: (url) => {
        if (queryOf(url).get('status') !== 'on_job') {
          throw new Error(`在职骑手须落到 /rider?status=on_job。实际 ${url}`);
        }
        assertSiteMonthInUrl(url, { siteId, month, label: '在职骑手' });
      },
    },
    {
      testId: INSIGHT_CARD_IDS.monthOrders,
      path: /\/rider-salary\/order/,
      check: (url) => {
        assertSiteMonthInUrl(url, { siteId, month, monthViaWindow: true, label: '本月单量' });
        if (!queryOf(url).get('date_from') || !queryOf(url).get('date_to')) {
          throw new Error(`本月单量须带 date_from+date_to。实际 ${url}`);
        }
      },
    },
    {
      testId: INSIGHT_CARD_IDS.validOrders,
      path: /\/rider-salary\/order/,
      check: (url) => {
        assertSiteMonthInUrl(url, { siteId, month, monthViaWindow: true, label: '有效单量' });
      },
    },
    {
      testId: INSIGHT_CARD_IDS.estimatedGross,
      path: /\/rider-salary\/period/,
      check: (url) => {
        assertSiteMonthInUrl(url, { siteId, month, label: '预计应发' });
      },
    },
    {
      testId: INSIGHT_CARD_IDS.pendingAdvances,
      path: /\/rider-salary\/advance/,
      check: (url) => {
        if (queryOf(url).get('status') !== 'pending') {
          throw new Error(`待审核预支只补站/月，status 须仍为 pending。实际 ${url}`);
        }
        assertSiteMonthInUrl(url, { siteId, month, label: '待审核预支' });
      },
    },
    {
      testId: INSIGHT_CARD_IDS.toPayAdvances,
      path: /\/rider-salary\/advance/,
      check: (url) => {
        if (queryOf(url).get('status') !== 'to_pay') {
          throw new Error(`待发放预支只补站/月，status 须仍为 to_pay。实际 ${url}`);
        }
        assertSiteMonthInUrl(url, { siteId, month, label: '待发放预支' });
      },
    },
  ];

  for (const card of cards) {
    await page.goto(
      `${config.adminUrl}/rider-salary/dashboard?site_id=${siteId}&month=${month}`,
      { waitUntil: 'networkidle', timeout: 60000 },
    );
    await requireTestId(page, card.testId, `未见 #27 卡 ${card.testId}`);
    await page.getByTestId(card.testId).first().click();
    const url = await waitPath(page, card.path);
    card.check(url);
  }

  await page.goto(
    `${config.adminUrl}/rider-salary/dashboard?month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  await requireTestId(page, INSIGHT_CARD_IDS.monthOrders, '无站仍须见本月单量卡');
  await page.getByTestId(INSIGHT_CARD_IDS.monthOrders).first().click();
  const noSiteUrl = await waitPath(page, /\/rider-salary\/order/);
  assertSiteMonthInUrl(noSiteUrl, {
    month,
    siteOptional: true,
    monthViaWindow: true,
    label: '无站仍带月·本月单量',
  });

  await page.unroute('**/api/v1/rider-salary/dashboard/summary**').catch(() => {});
  await page.route('**/api/v1/rider-salary/dashboard/summary**', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.continue();
      return;
    }
    const res = await route.fetch();
    const json = await res.json();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...json,
        data: {
          ...(json?.data || {}),
          cards: {
            on_job_riders: 0,
            month_order_count: 0,
            month_valid_order_count: 0,
            estimated_gross: '0.00',
            pending_advances: 0,
            to_pay_advances: 0,
          },
          attention: [],
          trend: [],
          top_riders: { top: [], bottom: [] },
        },
      }),
    });
  });
  await page.goto(
    `${config.adminUrl}/rider-salary/dashboard?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  await requireTestId(page, 'dashboard-empty-import', '未见 #27 空态 dashboard-empty-import，不得 skip');
  const empty = page.getByTestId('dashboard-empty-import').first();
  const emptyText = await empty.innerText();
  if (!EMPTY_IMPORT_COPY.test(emptyText)) {
    throw new Error(`空态 CTA 须为「去导入订单」。实际 ${emptyText}`);
  }
  await empty.click();
  const emptyUrl = await waitPath(page, /\/rider-salary\/order/);
  assertSiteMonthInUrl(emptyUrl, { siteId, month, monthViaWindow: true, label: '空态去导入订单' });

  await page.unroute('**/api/v1/rider-salary/dashboard/summary**').catch(() => {});
  await page.route('**/api/v1/rider-salary/dashboard/summary**', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.continue();
      return;
    }
    const res = await route.fetch();
    const json = await res.json();
    const data = json?.data || {};
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...json,
        data: {
          ...data,
          cards: {
            on_job_riders: 4,
            month_order_count: 12,
            month_valid_order_count: 10,
            estimated_gross: '8200.00',
            pending_advances: 1,
            to_pay_advances: 1,
          },
          top_riders: {
            top: [{ rider_id: 41, job_no: 'FIX_C03_R1', name: '金标C03', order_count: 20 }],
            bottom: [{ rider_id: 9, job_no: 'FIX_C17_R1', name: '换绑夹具', order_count: 1 }],
          },
        },
      }),
    });
  });
  await page.goto(
    `${config.adminUrl}/rider-salary/dashboard?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  await requireTestId(page, 'dashboard-top-riders', '未见 dashboard-top-riders');
  await page.getByTestId('dashboard-top-riders').locator('tr, .ant-table-row').nth(1).click();
  const calUrl = await waitPath(page, /\/rider-salary\/calendar/);
  assertSiteMonthInUrl(calUrl, { siteId, month, label: 'Top/低产进日历' });
  if (!queryOf(calUrl).get('rider_id')) {
    throw new Error(`Top 须带 rider_id。实际 ${calUrl}`);
  }

  riderReqs.length = 0;
  await page.goto(
    `${config.adminUrl}/rider-salary/rider?status=on_job&site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  await requireTestId(page, 'rider-list-status-scope', '未见 rider-list-status-scope');
  await page.waitForTimeout(800);
  const consumed = riderReqs.some((url) => queryOf(url).get('status') === 'on_job');
  if (!consumed) {
    throw new Error(
      `在职列表须消费 ?status=on_job。忽略 query 仍全量 = FAIL。实际：${riderReqs.join(' | ') || '(无)'}`,
    );
  }
  const listed = await fetchRiders(config.apiUrl, token, {
    site_id: siteId,
    status: 'on_job',
    page: '1',
    size: '50',
  });
  const leaked = listed.items.filter((row) => row.status && row.status !== 'on_job');
  if (leaked.length) {
    throw new Error(`GET /riders?status=on_job 仍含非在职：${leaked.map((r) => r.job_no || r.status).join('、')}`);
  }

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-dashboard-insight-card-scope');
}
