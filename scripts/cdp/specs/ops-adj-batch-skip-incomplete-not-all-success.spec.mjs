/** CDP: ops-adj-batch-skip-incomplete-not-all-success — 批量奖惩半填行必须说真话
 * 必须走批量模态 + 半填行。夹具：3 行，2 行完整、1 行半填（骑手+日期、无科目）。
 * 存在半填行仍只 toast「批量录入成功」= FAIL。写成整批 422 = FAIL。
 * 不重锁 Cycle 5 手工双计闸，不重锁 Cycle 14 向导跳过错误行。
 */
import {
  FIXTURE_BATCH_CREATED,
  FIXTURE_BATCH_SKIPPED,
  MUST4_INCOMPLETE_HOOKS,
  MUST4_MODAL_HOOKS,
  MUST4_RESULT_HOOKS,
  assertBatchSkipIncomplete,
  assertLockedGoldUnchanged,
  pickAntOption,
  requireHooks,
  siteMonth,
} from '../cycle15-lib.mjs';

export const name = 'ops-adj-batch-skip-incomplete-not-all-success';

async function openBatchModal(page) {
  await page.getByRole('button', { name: /批量录入/ }).first().click();
  const dialog = page
    .getByTestId('adj-batch-modal')
    .or(page.getByRole('dialog').filter({ hasText: /批量录入奖惩/ }))
    .first();
  try {
    await dialog.waitFor({ state: 'visible', timeout: 20000 });
  } catch {
    throw new Error('必须走批量模态。未见「批量录入奖惩」= FAIL，不得 skip');
  }
  return dialog;
}

async function ensureThreeRows(page, dialog) {
  const add = dialog.getByRole('button', { name: /新增一行/ });
  for (let i = 0; i < 2; i += 1) {
    if (await add.count()) await add.first().click();
  }
}

async function fillCompleteRow(page, row, { date, amount }) {
  const rider = row.locator('.ant-select').first();
  if (await rider.count()) {
    await rider.click();
    const opt = page.locator('.ant-select-dropdown:visible .ant-select-item-option').first();
    await opt.waitFor({ state: 'visible', timeout: 15000 });
    await opt.click();
  } else {
    throw new Error('半填夹具须能选骑手。钩子缺失即红，不得 skip');
  }
  const dateInput = row.locator('input').filter({ has: page.locator('[placeholder], .ant-picker-input input') }).first()
    .or(row.locator('.ant-picker input'))
    .first();
  if (await dateInput.count()) {
    await dateInput.click();
    await dateInput.fill(date);
    await dateInput.press('Enter');
  } else {
    throw new Error('半填夹具须能填日期。不得 skip');
  }
  const subject = row.locator('.ant-select').nth(1);
  if (await subject.count()) {
    await pickAntOption(page, row.locator('td').nth(2).or(subject), /./);
  } else {
    throw new Error('完整行须能选科目。不得 skip');
  }
  const amountInput = row.locator('.ant-input-number-input, input[role=spinbutton]').first();
  if (await amountInput.count()) await amountInput.fill(String(amount));
  const remark = row.locator('input:not(.ant-input-number-input)').last();
  if (await remark.count()) await remark.fill('Cycle15 完整行');
}

async function fillIncompleteRow(page, row, { date }) {
  const rider = row.locator('.ant-select').first();
  if (await rider.count()) {
    await rider.click();
    const opt = page.locator('.ant-select-dropdown:visible .ant-select-item-option').first();
    await opt.waitFor({ state: 'visible', timeout: 15000 });
    await opt.click();
  }
  const dateInput = row.locator('.ant-picker input').first();
  if (await dateInput.count()) {
    await dateInput.click();
    await dateInput.fill(date);
    await dateInput.press('Enter');
  }
}

export async function run({ page, helpers, config }) {
  assertLockedGoldUnchanged();
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const { siteId, month, siteCode } = siteMonth();

  let batchBody = null;
  let batchStatus = null;
  page.on('request', (req) => {
    if (req.method() === 'POST' && /\/adjustments\/batch/.test(req.url())) {
      try {
        batchBody = JSON.parse(req.postData() || '{}');
      } catch {
        batchBody = { raw: req.postData() };
      }
    }
  });
  page.on('response', (res) => {
    if (res.request().method() === 'POST' && /\/adjustments\/batch/.test(res.url())) {
      batchStatus = res.status();
    }
  });

  await page.goto(`${config.adminUrl}/rider-salary/adjustment?site_id=${siteId}`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  const dialog = await openBatchModal(page);
  await requireHooks(
    page,
    MUST4_MODAL_HOOKS,
    '未见 ops-adj-batch-skip-incomplete-not-all-success / adj-batch-modal。必须走批量模态 + 半填行，不得 skip。禁止写成整批 422',
  );

  const siteBox = dialog.locator('.ant-select').first();
  if (await siteBox.count()) {
    await pickAntOption(page, dialog, new RegExp(siteCode));
  }
  await ensureThreeRows(page, dialog);
  const tableRows = dialog.locator('tbody tr');
  const rowCount = await tableRows.count();
  if (rowCount < 3) {
    throw new Error(`夹具须 3 行（2 完整 + 1 半填）。实际 ${rowCount}。不得 skip`);
  }
  await fillCompleteRow(page, tableRows.nth(0), { date: `${month}-10`, amount: 10 });
  await fillCompleteRow(page, tableRows.nth(1), { date: `${month}-11`, amount: 20 });
  await fillIncompleteRow(page, tableRows.nth(2), { date: `${month}-12` });
  await requireHooks(
    page,
    MUST4_INCOMPLETE_HOOKS,
    '未见 adj-batch-incomplete-row。夹具第三行须是半填（骑手+日期、无科目）。空的「新增一行」空白行可不计，不得 skip',
  );

  await page.getByRole('button', { name: /提交批量录入/ }).click();
  const started = Date.now();
  while (batchBody == null && Date.now() - started < 30000) {
    await page.waitForTimeout(200);
  }
  if (batchStatus === 422) {
    throw new Error('升整批 422 = 本席 FAIL。半填行须跳过并说真话，不得写成整批 422');
  }
  const sent = Array.isArray(batchBody?.items) ? batchBody.items.length : null;
  if (sent != null && sent !== FIXTURE_BATCH_CREATED) {
    throw new Error(
      `后端只应收到 2 条完整行。实际 ${sent}。半填行不得静默丢掉后只报整表成功，也不得整表入库`,
    );
  }

  await requireHooks(
    page,
    MUST4_RESULT_HOOKS,
    '提交后须见 adj-batch-created-count / adj-batch-skipped-count。存在半填行仍只 toast「批量录入成功」= FAIL，不得 skip',
  );
  const createdText = await page.getByTestId('adj-batch-created-count').innerText();
  const skippedText = await page.getByTestId('adj-batch-skipped-count').innerText();
  const resultText = await page
    .getByTestId('ops-adj-batch-skip-incomplete-not-all-success')
    .innerText()
    .catch(async () => `${createdText}\n${skippedText}\n${await page.locator('body').innerText()}`);
  const created = Number((createdText.match(/\d+/) || [''])[0]);
  const skipped = Number((skippedText.match(/\d+/) || [''])[0]);
  if (created !== FIXTURE_BATCH_CREATED || skipped < FIXTURE_BATCH_SKIPPED) {
    throw new Error(
      `须可见已录入 2、跳过未完整 1。实际已录入「${createdText}」跳过「${skippedText}」。不得只剩「批量录入成功」`,
    );
  }
  assertBatchSkipIncomplete(`${resultText}\n${createdText}\n${skippedText}`, {
    created: FIXTURE_BATCH_CREATED,
    skipped: FIXTURE_BATCH_SKIPPED,
  });

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-adj-batch-skip-incomplete-not-all-success');
}
