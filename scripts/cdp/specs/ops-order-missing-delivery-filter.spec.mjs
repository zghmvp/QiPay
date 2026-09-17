/** CDP: ops-order-missing-delivery-filter — 订单可筛已完成且送达为空（PR #16） */
import {
  MISS_ORDER_DAY,
  MISS_ORDER_NO,
  apiFetch,
  isApiAbsent,
  siteLevelOpenPeriod,
  siteMonth,
} from '../cycle1-lib.mjs';

export const name = 'ops-order-missing-delivery-filter';

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();

  const qs = new URLSearchParams({
    page: '1',
    size: '50',
    site_id: String(siteId),
    date_from: MISS_ORDER_DAY,
    date_to: MISS_ORDER_DAY,
    missing_delivery: '1',
  });
  const { res, json } = await apiFetch(
    config.apiUrl,
    token,
    'GET',
    `/api/v1/rider-salary/orders?${qs}`,
  );
  if (isApiAbsent(res, json)) {
    throw new Error(
      `GET /orders?missing_delivery=1 接口不存在 HTTP ${res.status}。PR #16 应已落地该筛，忽略参数仍全量 = FAIL`,
    );
  }
  if (!res.ok) {
    throw new Error(
      `GET /orders?missing_delivery=1 失败 HTTP ${res.status}：${JSON.stringify(json).slice(0, 200)}`,
    );
  }
  const items = json?.data?.items || [];
  const hit = items.find((row) => row.order_no === MISS_ORDER_NO);
  if (!hit) {
    throw new Error(
      `missing_delivery=1 未返回夹具 ${MISS_ORDER_NO}。请先 seed；列表不得把参数吞掉仍返回全量`,
    );
  }
  if (hit.deliver_time) {
    throw new Error(`夹具 ${MISS_ORDER_NO} 仍有送达时间，seed 未把 deliver_time 置空`);
  }
  const leaked = items.filter((row) => row.deliver_time);
  if (leaked.length) {
    throw new Error(
      `缺送达筛仍带出有送达单 ${leaked[0].order_no}（PR #16 须真正过滤 completed ∧ deliver_time IS NULL）`,
    );
  }

  const unfiltered = await apiFetch(
    config.apiUrl,
    token,
    'GET',
    `/api/v1/rider-salary/orders?${new URLSearchParams({
      page: '1',
      size: '50',
      site_id: String(siteId),
      date_from: MISS_ORDER_DAY,
      date_to: MISS_ORDER_DAY,
    })}`,
  );
  if (unfiltered.res.ok) {
    const all = unfiltered.json?.data?.items || [];
    const withDelivery = all.filter((row) => row.deliver_time);
    if (withDelivery.length && items.length >= all.length) {
      throw new Error('missing_delivery=1 与未筛列表等长且含有送达单：参数被忽略');
    }
  }

  await page.goto(
    `${config.adminUrl}/rider-salary/order?site_id=${siteId}&date_from=${MISS_ORDER_DAY}&date_to=${MISS_ORDER_DAY}&missing_delivery=1`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  const url = page.url();
  if (!/[?&]missing_delivery=1/.test(url) && !page.url().includes('missing_delivery')) {
    throw new Error(`订单页未消费 /order?missing_delivery=1：${url}`);
  }
  const body = await page.locator('body').innerText();
  if (!body.includes('已完成且送达为空') && !body.includes('缺送达')) {
    throw new Error('订单页未见筛「已完成且送达为空」');
  }
  if (!body.includes(MISS_ORDER_NO)) {
    throw new Error(`筛选后列表未见夹具单 ${MISS_ORDER_NO}`);
  }
  helpers.assertNoPaymentTaxCopy(body);
  await helpers.shot(page, 'cdp-ops-order-missing-delivery-filter');

  const period = await siteLevelOpenPeriod({
    apiUrl: config.apiUrl,
    token,
    siteId,
    month,
  });
  if (!period?.id) {
    throw new Error('未找到站点月周期，无法核对算薪页「看订单」');
  }
  await page.goto(`${config.adminUrl}/rider-salary/period/${period.id}/calculate`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  const missRow = page
    .getByTestId('period-calc-blockers')
    .locator('tr')
    .filter({ hasText: /送达时间为空|缺送达|已完成但送达/ });
  const failLook = page.getByTestId('period-calc-fail-order').first();
  if ((await missRow.count()) > 0) {
    await missRow.getByTestId('period-calc-blocker-fix').click();
    await page.waitForURL(/\/rider-salary\/order/, { timeout: 20000 });
    if (!page.url().includes('missing_delivery=1')) {
      throw new Error(`预检缺送达「看订单」未带 missing_delivery=1：${page.url()}`);
    }
  } else if ((await failLook.count()) > 0) {
    await failLook.click();
    await page.waitForURL(/\/rider-salary\/order/, { timeout: 20000 });
    if (!page.url().includes('missing_delivery=1')) {
      throw new Error(`失败「看订单」未带 missing_delivery=1：${page.url()}`);
    }
  } else {
    console.warn('WARN: 算薪页当前没有缺送达「看订单」行（夹具可能尚未算出 missing_delivery）');
  }
}
