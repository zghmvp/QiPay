/** CDP: ops-dashboard-abnormal-attention-landing — #27 异常查看全部 attention=1 + 站月窗 */
import { ATTENTION_ORDER_NOS, ATT_ABNORMAL_NO, ATT_OVERTIME_NO } from '../cycle2-lib.mjs';
import {
  assertSiteMonthInUrl,
  fetchDashboardSummary,
  fetchOrders,
  queryOf,
  requireTestId,
  siteMonth,
  waitPath,
} from '../cycle4-lib.mjs';

export const name = 'ops-dashboard-abnormal-attention-landing';

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();
  const dateFrom = `${month}-01`;
  const dateTo = `${month}-30`;

  const summary = await fetchDashboardSummary(config.apiUrl, token, { siteId, month });
  const block = (summary?.attention || []).find((row) => row.key === 'abnormal_orders');
  if (block?.link) {
    if (!String(block.link).includes('attention=1') && !String(block.link).includes('attention=true')) {
      throw new Error(`异常订单 link 须 attention=1，不得只吃 status=abnormal。实际 ${block.link}`);
    }
    if (String(block.link).includes('missing_delivery')) {
      throw new Error(`缺送达不要并进本筛：${block.link}`);
    }
  }

  const attention = await fetchOrders(config.apiUrl, token, {
    site_id: siteId,
    date_from: dateFrom,
    date_to: dateTo,
    attention: '1',
    page: '1',
    size: '100',
  });
  if ([404, 405, 422, 501].includes(attention.res.status)) {
    throw new Error(`GET /orders?attention=1 HTTP ${attention.res.status}，不得 skip`);
  }
  const attNos = new Set(attention.items.map((row) => row.order_no));
  if (ATTENTION_ORDER_NOS.every((no) => !attNos.has(no)) && attention.items.length === 0) {
    throw new Error(`夹具需关注单未进 attention 列表：${ATTENTION_ORDER_NOS.join('、')}`);
  }
  if (attNos.size && !attNos.has(ATT_OVERTIME_NO) && ATTENTION_ORDER_NOS.includes(ATT_OVERTIME_NO)) {
    const overtimeInItems = attention.items.some(
      (row) => row.status === 'completed' && Number(row.duration_min ?? 0) > 60,
    );
    if (!overtimeInItems && !attNos.has(ATT_OVERTIME_NO)) {
      throw new Error('attention 不得退化成只出 abnormal（超时 completed 须在）');
    }
  }

  const orderReqs = [];
  page.on('request', (req) => {
    if (req.method() === 'GET' && /\/api\/v1\/rider-salary\/orders\?/.test(req.url())) {
      orderReqs.push(req.url());
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
    const attention = Array.isArray(data.attention) ? [...data.attention] : [];
    const abnormal = {
      key: 'abnormal_orders',
      title: '异常订单',
      count: 2,
      link: `/rider-salary/order?status=abnormal`,
      items: [
        { order_no: ATT_OVERTIME_NO, status: 'completed', duration_min: 61 },
        { order_no: ATT_ABNORMAL_NO, status: 'abnormal', duration_min: 10 },
      ],
    };
    const idx = attention.findIndex((row) => row.key === 'abnormal_orders');
    if (idx >= 0) attention[idx] = abnormal;
    else attention.push(abnormal);
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
  await requireTestId(
    page,
    'ops-dashboard-abnormal-attention-landing',
    '未见 #27 块 ops-dashboard-abnormal-attention-landing',
  );
  await requireTestId(page, 'dashboard-abnormal-view-all', '未见 dashboard-abnormal-view-all');
  await page.getByTestId('dashboard-abnormal-view-all').first().click();

  const url = await waitPath(page, /\/rider-salary\/order/);
  if (!/attention=1|attention=true|status=__attention__/.test(url)) {
    throw new Error(`落地 URL 须 attention=1 或等价。实际 ${url}`);
  }
  if (/status=abnormal/.test(url) && !/attention=/.test(url)) {
    throw new Error(`落地不得再只吃 status=abnormal。实际 ${url}`);
  }
  assertSiteMonthInUrl(url, {
    siteId,
    month,
    monthViaWindow: true,
    label: '异常订单查看全部',
  });
  if (/missing_delivery=/.test(url)) throw new Error(`缺送达不要并进本筛：${url}`);

  await requireTestId(page, 'order-attention-active', '落地须见 order-attention-active');
  await page.waitForTimeout(800);
  const consumed = orderReqs.some((req) => {
    const q = queryOf(req);
    return q.get('attention') === '1' || q.get('attention') === 'true';
  });
  if (!consumed) {
    throw new Error(
      `订单列表须把 attention=true 传给 API，不得传 status=abnormal。实际：${orderReqs.join(' | ') || '(无)'}`,
    );
  }
  const leakedStatus = orderReqs.find((req) => queryOf(req).get('status') === 'abnormal');
  if (leakedStatus) {
    throw new Error(`列表请求不得传 status=abnormal：${leakedStatus}`);
  }

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-dashboard-abnormal-attention-landing');
}
