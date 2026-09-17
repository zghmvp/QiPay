/** CDP: cdp-admin-calendar-month-not-payslip — 顶栏是本月合计；芯片进该骑手该期条 */
import {
  CROSS_PERIOD_COPY,
  LOCKED_GOLD_FORBIDDEN,
  MONTH_TOTAL_COPY,
  PERIOD_PAYSLIP_COPY,
  assertChipGoesToPayslip,
  assertLockedGoldUnchanged,
  isPeriodDrawer,
  requireHooks,
  requireTestId,
  siteMonth,
  waitPath,
} from '../cycle13-lib.mjs';

export const name = 'cdp-admin-calendar-month-not-payslip';

export async function run({ page, helpers, config }) {
  assertLockedGoldUnchanged();
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const { siteId, month } = siteMonth();
  const riderId = process.env.CDP_RIDER_ID;
  if (!riderId) {
    throw new Error('日历顶栏须 CDP_RIDER_ID（该骑手半月结夹具），不得 skip');
  }

  await page.goto(
    `${config.adminUrl}/rider-salary/calendar?site_id=${siteId}&rider_id=${riderId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  // 顶栏异步；先等本月合计，勿在未开日抽屉时要求 calendar-view-period
  await requireHooks(
    page,
    [
      'cdp-admin-calendar-month-not-payslip',
      'calendar-month-total',
      'calendar-month-period-count',
      'calendar-period-chip',
    ],
    '未见 cdp-admin-calendar-month-not-payslip / calendar-month-total / calendar-period-chip，不得 skip',
  );

  const bar = page.getByTestId('cdp-admin-calendar-month-not-payslip').first();
  const barText = await bar.innerText();
  if (!MONTH_TOTAL_COPY.test(barText)) {
    throw new Error(`顶栏须能读出「本月合计」。只标应发/实发 = FAIL。实际：${barText.slice(0, 200)}`);
  }
  if (!CROSS_PERIOD_COPY.test(barText) && !/1\s*个周期|跨\s*1/.test(barText)) {
    throw new Error(`顶栏须标「跨 N 个周期」或「本月合计 / N 个周期」。实际：${barText.slice(0, 200)}`);
  }
  if (!/应发/.test(barText) || !/实发/.test(barText)) {
    throw new Error('卡片标题仍只写「应发」「实发」。改成「本期应发」= FAIL');
  }
  if (PERIOD_PAYSLIP_COPY.test(barText)) {
    throw new Error(`顶栏不得写成「本周期 / 本期工资条 / 本期应发」。实际：${barText.slice(0, 200)}`);
  }
  if (LOCKED_GOLD_FORBIDDEN.test(barText)) {
    throw new Error('金标 8200/7800/3500 已锁，不得出现 4629.33 / 预支 800');
  }

  const chip = page.getByTestId('calendar-period-chip').first();
  const chipPeriodId = await chip.getAttribute('data-period-id');
  const chipRiderId = await chip.getAttribute('data-rider-id');
  if (!chipPeriodId || !chipRiderId) {
    throw new Error('calendar-period-chip 须带 data-period-id + data-rider-id，不得 skip');
  }
  await chip.click();
  const chipUrl = await waitPath(page, /\/rider-salary\/payroll/, 20000);
  if (isPeriodDrawer(chipUrl)) {
    throw new Error(`芯片只开 /period?id= 全站抽屉 = FAIL。实际 ${chipUrl}`);
  }
  assertChipGoesToPayslip(chipUrl, {
    riderId: chipRiderId,
    periodId: chipPeriodId,
    label: '周期芯片',
  });

  await page.goto(
    `${config.adminUrl}/rider-salary/calendar?site_id=${siteId}&rider_id=${riderId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  const day = page.locator('[data-testid^="calendar-day-"]').first();
  if (await day.count()) {
    await day.click();
  }
  await requireTestId(page, 'calendar-view-period', '日抽屉「查看周期」钩子缺失即红，不得 skip');
  // 日抽屉动画未稳时 mask / 兄弟按钮会挡指针；钩子已在 DOM 即 force 点击
  const viewPeriod = page.getByTestId('calendar-view-period').first();
  await viewPeriod.waitFor({ state: 'visible', timeout: 15000 });
  await page
    .locator('.ant-drawer-open .ant-drawer-content-wrapper')
    .first()
    .waitFor({ state: 'visible', timeout: 15000 })
    .catch(() => {});
  await page
    .waitForFunction(
      () => !document.querySelector('.ant-drawer-mask-motion-appear-active, .ant-drawer-mask-motion-enter-active'),
      { timeout: 10000 },
    )
    .catch(() => {});
  await viewPeriod.scrollIntoViewIfNeeded().catch(() => {});
  await viewPeriod.click({ force: true });
  const viewUrl = await waitPath(page, /\/rider-salary\/payroll/, 20000);
  assertChipGoesToPayslip(viewUrl, {
    riderId,
    periodId: chipPeriodId,
    label: '查看周期',
  });

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-admin-calendar-month-not-payslip');
}
