/** CDP: ops-reverse-confirm-then-calc — 反冲确认必须写出将反冲范围，确认后落到该期算薪
 * 必须走反冲确认框 + 成功后该期算薪页。只断言文案 / 新开待补发 = FAIL。
 * 不重锁 Cycle 13 锁确认跳过人数 M。不改决策 29。
 */
import {
  MUST3_CONFIRM_HOOKS,
  MUST3_LANDING_HOOKS,
  assertLockedGoldUnchanged,
  assertReverseConfirmCounts,
  assertReverseConfirmThenCalc,
  clickRowAction,
  confirmVisibleDialog,
  fetchPeriods,
  fetchReversePreflight,
  requireHooks,
  siteMonth,
  waitPath,
} from '../cycle15-lib.mjs';

export const name = 'ops-reverse-confirm-then-calc';

export async function run({ page, helpers, config }) {
  assertLockedGoldUnchanged();
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();

  const listed = await fetchPeriods(config.apiUrl, token, { site_id: siteId, month });
  const period = (listed.items || []).find((row) =>
    ['locked', 'paid'].includes(String(row.status || '')),
  );
  if (!period?.id) {
    throw new Error('未见可反冲的已定稿/已发薪周期，不得 skip。本席必须走反冲确认框然后进该期算薪页');
  }

  const preflight = await fetchReversePreflight(config.apiUrl, token, period.id);
  for (const key of ['reversal_count', 'rider_count']) {
    if (preflight?.[key] == null && preflight?.involved_rider_count == null) {
      throw new Error(`预检须返回 ${key}。只有套话且无单数/人数 = FAIL。前端抄列表 rider_count = FAIL`);
    }
  }

  let reversed = false;
  page.on('request', (req) => {
    if (req.method() === 'POST' && new RegExp(`/periods/${period.id}/reverse`).test(req.url())) {
      reversed = true;
    }
  });

  await page.goto(
    `${config.adminUrl}/rider-salary/period?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  const rows = page.locator('.vxe-body--row, .vxe-table--body tr, tr');
  const row = rows
    .filter({ hasText: period.start_date || '' })
    .filter({ hasText: /反冲补发|锁账|已锁|已发薪|locked|paid/ })
    .first();
  const target = (await row.count())
    ? row
    : rows.filter({ hasText: period.start_date || String(period.id) }).first();
  if (!(await target.count())) {
    throw new Error('周期列表未见该期「反冲补发」。必须走确认框，不得 skip');
  }
  await clickRowAction(page, target, '反冲补发');

  await requireHooks(
    page,
    MUST3_CONFIRM_HOOKS,
    '未见 ops-reverse-confirm-then-calc / period-reverse-confirm / period-reverse-count / period-reverse-rider-count。只有套话且无单数/人数 = FAIL，不得 skip',
  );
  const confirmText = await page.getByTestId('period-reverse-confirm').innerText();
  const countText = await page.getByTestId('period-reverse-count').innerText();
  const riderText = await page.getByTestId('period-reverse-rider-count').innerText();
  assertReverseConfirmCounts(`${confirmText}\n${countText}\n${riderText}`, preflight, period.rider_count);

  await confirmVisibleDialog(page, /确认|确定|继续/);
  const reason = page.getByRole('dialog').filter({ hasText: /反冲补发原因/ });
  if (await reason.count()) {
    const input = reason.locator('textarea, input').first();
    if (await input.count()) await input.fill('Cycle 15 反冲确认后进算薪');
    await confirmVisibleDialog(page, /确认|确定|提交/);
  }

  const started = Date.now();
  while (!reversed && Date.now() - started < 30000) {
    await page.waitForTimeout(200);
  }
  if (!reversed) {
    throw new Error(
      '确认后未见 POST /reverse。只改确认文案、人还停在周期列表 = 补发办不完，本席 FAIL。禁止新开待补发',
    );
  }

  const landed = await waitPath(page, /\/rider-salary\/period\/\d+\/calculate/, 20000);
  assertReverseConfirmThenCalc(landed, period.id);
  await requireHooks(
    page,
    MUST3_LANDING_HOOKS,
    '确认后须进该期算薪页（period-calc-title）。停在周期列表且无该期算薪入口 = FAIL。reopened 合法。不得 skip',
  );
  if (/待补发/.test(await page.locator('body').innerText()) && !/\/calculate/.test(page.url())) {
    throw new Error('不新开「待补发」块。确认后必须进该 period_id 算薪页');
  }

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-reverse-confirm-then-calc');
}
