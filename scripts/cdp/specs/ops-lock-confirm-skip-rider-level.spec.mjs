/** CDP: ops-lock-confirm-skip-rider-level — 站点级锁确认写出冻结范围 + 决策 29 跳过人数 M */
import {
  MUST5_HOOKS,
  SKIP_RIDER_COPY,
  apiFetch,
  assertLockConfirmCopy,
  assertLockedGoldUnchanged,
  fetchPeriods,
  lockConfirmHintFromPreflight,
  requireHooks,
  siteMonth,
} from '../cycle13-lib.mjs';

export const name = 'ops-lock-confirm-skip-rider-level';

async function fetchLockPreflight(apiUrl, token, periodId) {
  const paths = [
    `/api/v1/rider-salary/periods/${periodId}/lock-preflight`,
    `/api/v1/rider-salary/periods/${periodId}/lock/preflight`,
  ];
  let last = null;
  for (const urlPath of paths) {
    last = await apiFetch(apiUrl, token, 'GET', urlPath);
    if (last.res.ok) return last.json?.data || last.json;
    if (![404, 405, 501].includes(last.res.status)) {
      throw new Error(
        `锁确认预检 HTTP ${last.res.status}：${JSON.stringify(last.json).slice(0, 300)}`,
      );
    }
  }
  throw new Error(
    `站点级锁确认预检缺失（须 lock_preflight）。前端自己数窗内人头 = FAIL。最后 ${last?.res?.status}`,
  );
}

export async function run({ page, helpers, config }) {
  assertLockedGoldUnchanged();
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();

  const listed = await fetchPeriods(config.apiUrl, token, { site_id: siteId, month });
  const siteLevel = (listed.items || []).find(
    (row) => Number(row.rider_id) === 0 || row.rider_id == null,
  );
  if (!siteLevel?.id) {
    throw new Error('未见 rider_id=0 的站点级周期，不得 skip。本席只验站点级锁确认');
  }

  const preflight = await fetchLockPreflight(config.apiUrl, token, siteLevel.id);
  for (const key of ['order_count', 'adjustment_count', 'payroll_count', 'lock_rider_count', 'skip_rider_count']) {
    if (preflight?.[key] == null) {
      throw new Error(`预检须返回 ${key}。人数=窗内全量且无跳过说明 = FAIL`);
    }
  }
  const expectedHint = lockConfirmHintFromPreflight(preflight);

  await page.goto(
    `${config.adminUrl}/rider-salary/period?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  const rows = page.locator('.vxe-body--row, .vxe-table--body tr, tr');
  const row = rows.filter({ hasText: siteLevel.start_date || '' }).first();
  const lockBtn = row.getByText('锁账', { exact: true });
  if (await lockBtn.count()) {
    await lockBtn.first().click();
  } else {
    const more = row.getByText(/更多|更多操作/);
    if (await more.count()) {
      await more.first().click();
      await page.getByRole('menuitem', { name: /^锁账$/ }).click();
    } else {
      throw new Error('未见站点级周期「锁账」，不得 skip');
    }
  }

  await requireHooks(
    page,
    MUST5_HOOKS,
    '未见 ops-lock-confirm-skip-rider-level / period-lock-confirm-hint / period-lock-skip-count。只有 rider_count = FAIL，不得 skip',
  );
  const hint = await page.getByTestId('period-lock-confirm-hint').innerText();
  const skip = await page.getByTestId('period-lock-skip-count').innerText();
  assertLockConfirmCopy(`${hint}\n${skip}`, preflight);
  if (!SKIP_RIDER_COPY.test(`${hint}${skip}`)) {
    throw new Error(`确认文案须出现跳过骑手级覆盖（M=${preflight.skip_rider_count} 仍须出现）`);
  }
  if (!hint.includes(String(preflight.order_count)) || !hint.includes(String(preflight.payroll_count))) {
    throw new Error(`确认数字须吃后端预检，不得前端自己数。期望含 ${expectedHint}`);
  }
  if (
    Number(preflight.lock_rider_count) + Number(preflight.skip_rider_count) > 0 &&
    Number(preflight.lock_rider_count) === Number(siteLevel.rider_count) &&
    Number(preflight.skip_rider_count) > 0 &&
    !SKIP_RIDER_COPY.test(hint + skip)
  ) {
    throw new Error('将锁人数不得等于窗内全量且无跳过说明。站长以为锁了其实跳过 = FAIL');
  }

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-lock-confirm-skip-rider-level');
}
