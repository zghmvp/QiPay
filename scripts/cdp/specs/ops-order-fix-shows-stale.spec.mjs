/** CDP: ops-order-fix-shows-stale — 纠错/补录成功必须写出需重算并落到覆盖该日的该期算薪
 * 必须走订单抽屉纠错或补录。API 绿替抽屉 = FAIL。只改 toast 无该期算薪入口 = FAIL。
 * 禁止写成「仍 422」或「跳过错误行」。禁止自动 calculate。
 */
import {
  MUST2_DRAWER_HOOKS,
  MUST2_SUCCESS_HOOKS,
  assertFixGotoCoveringCalc,
  assertFixShowsStale,
  assertLockedGoldUnchanged,
  assertNoImportCsvGreen,
  assertNoOrderApiGreen,
  clickRowAction,
  confirmVisibleDialog,
  fetchOrders,
  fetchPeriodForDate,
  monthFromDate,
  requireHooks,
  requireTestId,
  siteMonth,
  waitPath,
} from '../cycle15-lib.mjs';

export const name = 'ops-order-fix-shows-stale';

export async function run({ page, helpers, config }) {
  assertLockedGoldUnchanged();
  assertNoOrderApiGreen();
  assertNoImportCsvGreen();
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();

  const listed = await fetchOrders(config.apiUrl, token, {
    site_id: siteId,
    date_from: `${month}-01`,
    is_locked: false,
    page: 1,
    size: 20,
  });
  const order = (listed.items || []).find((row) => row.id && !row.is_locked);
  if (!order?.id) {
    throw new Error(
      '未见未锁已导入单，夹具须在未锁周期内改一条已导入单（改时长或备注即可）。不得 skip。禁止 API 绿替抽屉',
    );
  }

  let wroteViaDrawer = false;
  let autoCalc = false;
  page.on('request', (req) => {
    const method = req.method();
    const url = req.url();
    if (method === 'PUT' && /\/orders\/\d+/.test(url)) wroteViaDrawer = true;
    if (method === 'POST' && /\/orders\/?$/.test(url) && !/import/.test(url)) {
      wroteViaDrawer = true;
    }
    if (method === 'POST' && /\/periods\/\d+\/calculate/.test(url)) autoCalc = true;
  });

  await page.goto(
    `${config.adminUrl}/rider-salary/order?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  const rows = page.locator('.vxe-body--row, .vxe-table--body tr, tr');
  const row = rows.filter({ hasText: order.order_no || String(order.id) }).first();
  if (!(await row.count())) {
    throw new Error('订单列表未见该未锁单，须走订单抽屉纠错或补录。禁止 API 绿替，不得 skip');
  }
  await clickRowAction(page, row, '纠错');
  await requireHooks(
    page,
    MUST2_DRAWER_HOOKS,
    '未见 ops-order-fix-shows-stale / order-form-drawer。Must 2 必须走订单抽屉，禁止 API 绿替、禁止只断言 toast，不得 skip',
  );

  const drawer = page.getByTestId('order-form-drawer').first();
  const remark = drawer.locator('textarea').first();
  if (await remark.count()) {
    await remark.fill(`CDP-C15-FIX ${Date.now()}`);
  } else {
    const duration = drawer.locator('input[role=spinbutton], .ant-input-number-input').first();
    if (!(await duration.count())) {
      throw new Error('抽屉须能改时长或备注。夹具：未锁周期内改一条已导入单，不得 skip');
    }
    await duration.fill('12');
  }

  const confirmBtn = page.getByRole('button', { name: /确认|确定|保存/ }).last();
  await confirmBtn.click();
  const reason = page.getByRole('dialog').filter({ hasText: /纠错原因/ });
  if (await reason.count()) {
    const input = reason.locator('textarea, input').first();
    if (await input.count()) await input.fill('Cycle 15 纠错需重算');
    await confirmVisibleDialog(page, /确认|确定|提交/);
  }

  const started = Date.now();
  while (!wroteViaDrawer && Date.now() - started < 30000) {
    await page.waitForTimeout(200);
  }
  if (!wroteViaDrawer) {
    throw new Error(
      '订单抽屉提交后未见纠错/补录写请求。禁止 API 绿替抽屉。把本席写成「仍 422」或「跳过错误行」= FAIL',
    );
  }
  if (autoCalc) {
    throw new Error('纠错/补录不得自动 calculate。不引入 Celery。本席 FAIL');
  }

  await requireHooks(
    page,
    MUST2_SUCCESS_HOOKS,
    '成功反馈须见 order-fix-stale-copy / order-fix-goto-calc。只 toast「已纠错/已补录」且无「需重算」= FAIL。只改 toast 人还停在订单抽屉 = 本席仍 FAIL，不得 skip',
  );
  const stale = await page.getByTestId('order-fix-stale-copy').innerText();
  const feedback = await page.getByTestId('ops-order-fix-shows-stale').innerText().catch(async () => {
    return `${stale}\n${await page.locator('body').innerText()}`;
  });
  assertFixShowsStale(`${feedback}\n${stale}`);

  const covering = await fetchPeriodForDate(config.apiUrl, token, {
    siteId: order.site_id || siteId,
    date: order.biz_date,
    riderId: order.rider_id,
  });
  const goto = page.getByTestId('order-fix-goto-calc').first();
  const dataPeriod = await goto.getAttribute('data-period-id');
  if (
    covering?.period?.id &&
    dataPeriod &&
    String(dataPeriod) !== String(covering.period.id)
  ) {
    throw new Error(
      `按钮落到错期。覆盖该日的 period_id=${covering.period.id}，按钮 ${dataPeriod}。停在周期列表自己猜 = FAIL`,
    );
  }
  await goto.click();
  const landed = await waitPath(page, /\/rider-salary\/period/, 20000);
  assertFixGotoCoveringCalc(landed, {
    ...covering,
    site_id: order.site_id || covering?.site_id || siteId,
    start_date: covering?.start_date || covering?.period?.start_date || order.biz_date,
    month: monthFromDate(order.biz_date) || month,
  });
  if (/\/calculate/.test(landed)) {
    await requireTestId(
      page,
      'period-calc-title',
      '有覆盖期时须进该期算薪页。周期列表自己猜该进哪期 = FAIL，不得 skip',
    );
  }

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-order-fix-shows-stale');
}
