/** CDP: cdp-admin-day-drawer-not-daily-payslip — 日抽屉公式金额/净额不得读成当日应发
 * 只锁日面粒度文案。不验收 Cycle 13 芯片 / 查看周期进条。
 */
import {
  MUST5_HOOKS,
  assertDayDrawerNotPayslip,
  assertLockedGoldUnchanged,
  requireHooks,
  requireTestId,
  siteMonth,
} from '../cycle14-lib.mjs';

export const name = 'cdp-admin-day-drawer-not-daily-payslip';

export async function run({ page, helpers, config }) {
  assertLockedGoldUnchanged();
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const { siteId, month } = siteMonth();
  const riderId = process.env.CDP_RIDER_ID;
  if (!riderId) {
    throw new Error(
      '日抽屉须 CDP_RIDER_ID（半月结 P2 / 阶梯底薪日夹具）。钩子缺失不得 skip。本席不验收芯片进条',
    );
  }

  await page.goto(
    `${config.adminUrl}/rider-salary/calendar?site_id=${siteId}&rider_id=${riderId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  const day = page.locator('[data-testid^="calendar-day-"]').first();
  if (!(await day.count())) {
    throw new Error('日历未见日期格钩子，不得 skip。本席只验日抽屉，不点芯片 / 查看周期');
  }
  await day.click();
  await requireTestId(
    page,
    'cdp-admin-day-drawer-not-daily-payslip',
    '未见 cdp-admin-day-drawer-not-daily-payslip。日抽屉钩子缺失即红，不得 skip',
  );
  await requireHooks(
    page,
    MUST5_HOOKS,
    '未见 day-drawer-formula-amount / day-drawer-net / day-drawer-period-not-daily。无「周期项不落日 / 对账看条」= FAIL，不得 skip',
  );

  const drawer = page.getByTestId('cdp-admin-day-drawer-not-daily-payslip').first();
  const text = await drawer.innerText();
  assertDayDrawerNotPayslip(text);
  const formula = await page.getByTestId('day-drawer-formula-amount').innerText();
  const net = await page.getByTestId('day-drawer-net').innerText();
  const note = await page.getByTestId('day-drawer-period-not-daily').innerText();
  if (!/公式金额/.test(formula) && !/\d/.test(formula)) {
    throw new Error(`公式金额卡须能读出数字或中文标签。实际：${formula.slice(0, 120)}`);
  }
  if (!/净额/.test(net) && !/\d/.test(net)) {
    throw new Error(`净额卡须能读出数字或中文标签。实际：${net.slice(0, 120)}`);
  }
  if (!/周期项不落日|对账看条/.test(note)) {
    throw new Error(
      `日抽屉须标「周期项不落日 / 对账看条」。摊日 / 再做一套当日应发−代扣−预支 = FAIL。实际：${note.slice(0, 200)}`,
    );
  }

  helpers.assertNoPaymentTaxCopy(text);
  await helpers.shot(page, 'cdp-admin-day-drawer-not-daily-payslip');
}
