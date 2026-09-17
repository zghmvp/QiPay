/** CDP: cdp-admin-day-uncalculated-not-zero — 未算薪日公式金额/净额不得读成今日 0 提成
 * 只锁未算薪日的空态/主数字。
 * 不验收 Cycle 13 芯片 / 查看周期进条。
 * 不验收 Cycle 14 已算日「周期项不落日 / 对账看条」。
 * 为对齐去现场 calculate 落库 / 摊周期项 / 改金标三数 = FAIL。
 */
import {
  FIXTURE_DAY,
  MUST5_HOOKS,
  MUST5_ORDER_HOOKS,
  assertDayUncalculatedNotZero,
  assertLockedGoldUnchanged,
  assertWithholdNotInDailyManual,
  requireHooks,
  requireTestId,
  siteMonth,
} from '../cycle15-lib.mjs';

export const name = 'cdp-admin-day-uncalculated-not-zero';

export async function run({ page, helpers, config }) {
  assertLockedGoldUnchanged();
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const { siteId, month } = siteMonth();
  const riderId = process.env.CDP_RIDER_ID;
  if (!riderId) {
    throw new Error(
      '日抽屉须 CDP_RIDER_ID（当日 ≥1 完成单、该骑手该期尚未 calculate、无 daily cache）。钩子缺失不得 skip。本席不验收芯片进条，不验收已算日周期项不落日',
    );
  }
  const day = process.env.CDP_DAY || FIXTURE_DAY;

  let calculated = false;
  page.on('request', (req) => {
    if (req.method() === 'POST' && /\/periods\/\d+\/calculate/.test(req.url())) {
      calculated = true;
    }
  });

  await page.route('**/api/v1/rider-salary/calendar/day**', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.continue();
      return;
    }
    const res = await route.fetch();
    const json = await res.json();
    const data = json?.data || {};
    const orders = Array.isArray(data.orders) && data.orders.length
      ? data.orders
      : [
          {
            id: 151016,
            order_no: 'C15-UNC-001',
            status: 'completed',
            amount: '12.00',
            details: [],
          },
        ];
    const totals = {
      ...(data.totals || {}),
      order_count: Math.max(Number(data.totals?.order_count) || 0, 1),
      formula_amount: data.totals?.formula_amount ?? '0.00',
      manual_bonus: data.totals?.manual_bonus ?? '0.00',
      manual_penalty: data.totals?.manual_penalty ?? '0.00',
      net: data.totals?.net ?? '0.00',
    };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...json,
        data: {
          ...data,
          has_daily_cache: false,
          calculated: false,
          orders: orders.map((row) => ({ ...row, details: row.details || [] })),
          daily_items: [],
          totals,
        },
      }),
    });
  });

  await page.goto(
    `${config.adminUrl}/rider-salary/calendar?site_id=${siteId}&rider_id=${riderId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  const cell = page.locator(`[data-testid="calendar-day-${day}"]`).or(
    page.locator('[data-testid^="calendar-day-"]').first(),
  );
  if (!(await cell.count())) {
    throw new Error('日历未见日期格。本席只验未算薪日抽屉空态，不点芯片 / 查看周期，不得 skip');
  }
  await cell.first().click();
  await requireTestId(
    page,
    'cdp-admin-day-uncalculated-not-zero',
    '未见 cdp-admin-day-uncalculated-not-zero。未算薪日钩子缺失即红，不得 skip。本席不验收 Cycle 13 芯片，不验收 Cycle 14 已算日周期项不落日',
  );
  await requireHooks(
    page,
    MUST5_HOOKS,
    '未见 day-drawer-formula-amount / day-drawer-net / day-drawer-uncalculated。主数字 0.00 且无「未算薪」= FAIL，不得 skip',
  );

  const drawer = page.getByTestId('cdp-admin-day-uncalculated-not-zero').first();
  const drawerText = await drawer.innerText();
  const formula = await page.getByTestId('day-drawer-formula-amount').innerText();
  const net = await page.getByTestId('day-drawer-net').innerText();
  const note = await page.getByTestId('day-drawer-uncalculated').innerText();

  const ordersTab = drawer.getByRole('tab', { name: /订单/ });
  if (await ordersTab.count()) await ordersTab.first().click();
  const expand = drawer.locator('.ant-table-row-expand-icon, button[aria-label*=expand]').first();
  let orderText = '';
  if (await expand.count()) {
    await expand.click();
    await requireHooks(
      page,
      MUST5_ORDER_HOOKS,
      '订单展开须见 day-drawer-order-not-in-calc。只写「无命中项」= FAIL，不得 skip',
    );
    orderText = await page.getByTestId('day-drawer-order-not-in-calc').innerText();
  } else {
    orderText = await drawer.innerText();
    await requireHooks(
      page,
      MUST5_ORDER_HOOKS,
      '同日订单展开须能读出尚未进本次算薪。只写「无命中项」= FAIL，不得 skip',
    );
    orderText += `\n${await page.getByTestId('day-drawer-order-not-in-calc').innerText()}`;
  }

  assertDayUncalculatedNotZero({
    drawerText: `${drawerText}\n${note}`,
    formulaText: formula,
    netText: net,
    orderText,
  });
  assertWithholdNotInDailyManual(drawerText, {
    hasWithhold: /代扣/.test(drawerText) || (await page.getByTestId('day-drawer-withhold-hint').count()) > 0,
  });

  if (calculated) {
    throw new Error('为对齐去现场 calculate 落库 = FAIL。无 cache 时空态不要现场算薪');
  }

  helpers.assertNoPaymentTaxCopy(drawerText);
  await helpers.shot(page, 'cdp-admin-day-uncalculated-not-zero');
}
