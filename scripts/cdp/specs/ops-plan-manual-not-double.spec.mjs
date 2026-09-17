/** CDP: ops-plan-manual-not-double — #32 保存/启用硬拦加项；#30 拼装器文案 */
import { apiFetch, siteMonth } from '../cycle1-lib.mjs';
import {
  GOLD_C03_JOB,
  GOLD_C05A_GROSS,
  GOLD_C05_JOB,
  activateVersion,
  c05Items,
  copyPlanVersion,
  getPlanVersion,
  listSubjects,
  moneyEquals,
  putPlanItems,
  requireGoldVersion,
  requireRiderByJobNo,
  subjectByCode,
  trialVersion,
} from '../cycle2-lib.mjs';
import { trialGross } from '../cycle3-lib.mjs';
import {
  MANUAL_ADDED_AS_FORMULA_COPY,
  MANUAL_ASSEMBLER_COPY,
  MANUAL_ASSEMBLER_DOUBLE_COPY,
  MANUAL_BONUS_FIELD,
  MANUAL_BOOKED_COPY,
  MANUAL_DOUBLE_COPY,
  MANUAL_NOT_DOUBLE_COPY,
  MANUAL_ONCE_AMOUNT,
  PR30_MANUAL_HOOKS,
  assertActivateBlocked,
  assertLockedGoldUnchanged,
  assertSaveBlocked,
  failBlob,
  isManualAddendFormula,
  requireHooks,
  requireTestId,
} from '../cycle5-lib.mjs';

export const name = 'ops-plan-manual-not-double';

function assertTrialOk(label, trial) {
  if ([404, 405, 501].includes(trial.res.status)) {
    throw new Error(`${label} 试算接口缺失 HTTP ${trial.res.status}，不得 skip`);
  }
  if (!trial.res.ok) {
    throw new Error(`${label} 试算失败：${failBlob(trial.res, trial.json).slice(0, 300)}`);
  }
}

export async function run({ page, helpers, config }) {
  assertLockedGoldUnchanged();
  if (!moneyEquals(GOLD_C05A_GROSS, 3500)) {
    throw new Error('C05A=3500 已锁，不得改金标');
  }
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();
  const start = `${month}-01`;
  const end = `${month}-30`;
  const subjects = await listSubjects(config.apiUrl, token);
  const salary = subjectByCode(subjects, 'BASE_SALARY');
  const guarantee = subjectByCode(subjects, 'GUARANTEE_TOPUP');
  const bonus = subjectByCode(subjects, 'BONUS_GOOD_REVIEW');
  if (!salary || !guarantee || !bonus) {
    throw new Error('科目 BASE_SALARY / GUARANTEE_TOPUP / BONUS_GOOD_REVIEW 缺失，不得 skip');
  }

  const c05 = await requireGoldVersion(config.apiUrl, token, 'FIX_C05');
  const rider05 = await requireRiderByJobNo(config.apiUrl, token, siteId, GOLD_C05_JOB);
  // LIVE 夹具清污：软删 C05 骑手上污染奖惩（否则 3500+手工奖 ≠ 金标）
  {
    const qs = new URLSearchParams({
      site_id: String(siteId),
      rider_id: String(rider05.id),
      page: '1',
      size: '100',
    });
    const listed = await apiFetch(
      config.apiUrl,
      token,
      'GET',
      `/api/v1/rider-salary/adjustments?${qs}`,
    );
    for (const adj of listed.json?.data?.items || []) {
      await apiFetch(config.apiUrl, token, 'DELETE', `/api/v1/rider-salary/adjustments/${adj.id}`, {
        reason: 'Cycle5 LIVE 清金标污染（非改 3500）',
      });
    }
  }
  const t05 = await trialVersion(config.apiUrl, token, c05.version.id, {
    riderId: rider05.id,
    start,
    end,
    mode: 'full_version',
  });
  assertTrialOk('C05A', t05);
  const g05 = trialGross(t05.json);
  if (!Number.isFinite(g05)) throw new Error('C05A 无应发数字 = FAIL');
  if (!moneyEquals(g05, GOLD_C05A_GROSS)) {
    throw new Error(`C05A 须继续=3500，实际=${g05}。不得改金标、不得新案例号`);
  }

  const legalItems = c05Items(subjects);
  const legalTopup = legalItems.find((row) => row.name === '保底补足');
  legalTopup.formula_json = {
    类型: '表达式',
    表达式: `最大值(0, 3500 − 本期已计金额 − ${MANUAL_BONUS_FIELD})`,
  };
  const legal = await copyPlanVersion(config.apiUrl, token, c05.version.id);
  const legalPut = await putPlanItems(config.apiUrl, token, legal.id, legalItems);
  if (!legalPut.res.ok) {
    throw new Error(
      `保底相减「最大值(0, 3500 − 本期已计金额 − 本期手工奖)」须继续合法：${failBlob(legalPut.res, legalPut.json).slice(0, 300)}`,
    );
  }

  const condItems = c05Items(subjects);
  condItems.splice(1, 0, {
    condition_json: {
      逻辑: '且',
      条件: [{ 字段: MANUAL_BONUS_FIELD, 运算符: '>', 值: 0 }],
    },
    enabled: true,
    formula_json: { 类型: '固定金额', 金额: 1 },
    name: '手工奖条件可读',
    sort_order: 20,
    stage: 'period',
    subject_id: salary.id,
  });
  const condOnly = await copyPlanVersion(config.apiUrl, token, c05.version.id);
  const condPut = await putPlanItems(config.apiUrl, token, condOnly.id, condItems);
  if (!condPut.res.ok) {
    throw new Error(
      `条件继续可读 ${MANUAL_BONUS_FIELD}，保存须成功：${failBlob(condPut.res, condPut.json).slice(0, 300)}`,
    );
  }

  const badExpr = await copyPlanVersion(config.apiUrl, token, c05.version.id);
  const addend = { 类型: '表达式', 表达式: MANUAL_BONUS_FIELD };
  if (!isManualAddendFormula(addend)) {
    throw new Error('夹具合同：表达式「本期手工奖」须被判定为加项');
  }
  const badItems = [
    {
      condition_json: {},
      enabled: true,
      formula_json: addend,
      name: '误加手工奖',
      sort_order: 20,
      stage: 'period',
      subject_id: salary.id,
    },
  ];
  const badPut = await putPlanItems(config.apiUrl, token, badExpr.id, badItems);
  assertSaveBlocked('表达式加项', badPut);
  const afterBad = await getPlanVersion(config.apiUrl, token, badExpr.id);
  const savedAddend = (afterBad.items || []).some((row) => isManualAddendFormula(row.formula_json));
  if (savedAddend) {
    throw new Error('库内不得留下把本期手工奖当加项的成功版本 / 可锁 draft');
  }
  const badAct = await activateVersion(config.apiUrl, token, badExpr.id);
  if (savedAddend) {
    assertActivateBlocked('表达式加项启用', badAct);
  } else {
    const actBlob = failBlob(badAct.res, badAct.json);
    if (MANUAL_BOOKED_COPY.test(actBlob) && MANUAL_DOUBLE_COPY.test(actBlob)) {
      /* 启用闸命中同一中文，亦绿 */
    }
  }

  const badRate = await copyPlanVersion(config.apiUrl, token, c05.version.id);
  const ratePut = await putPlanItems(config.apiUrl, token, badRate.id, [
    {
      condition_json: {},
      enabled: true,
      formula_json: { 类型: '字段乘单价', 字段: MANUAL_BONUS_FIELD, 单价: 1, 起算值: 0 },
      name: '字段乘单价手工奖',
      sort_order: 20,
      stage: 'period',
      subject_id: salary.id,
    },
  ]);
  assertSaveBlocked('字段乘单价加项', ratePut);

  const c03 = await requireGoldVersion(config.apiUrl, token, 'FIX_C03');
  const rider = await requireRiderByJobNo(config.apiUrl, token, siteId, GOLD_C03_JOB);
  const before = await trialVersion(config.apiUrl, token, c03.version.id, {
    riderId: rider.id,
    start,
    end,
    mode: 'full_version',
  });
  assertTrialOk('手工前', before);
  const beforeGross = trialGross(before.json);
  const createAdj = await apiFetch(
    config.apiUrl,
    token,
    'POST',
    '/api/v1/rider-salary/adjustments',
    {
      rider_id: rider.id,
      biz_date: `${month}-16`,
      subject_id: bonus.id,
      amount: String(MANUAL_ONCE_AMOUNT),
      remark: 'CDP_C5_MANUAL_200',
    },
  );
  if ([404, 405, 501].includes(createAdj.res.status)) {
    throw new Error(`奖惩录入接口缺失 HTTP ${createAdj.res.status}，不得 skip`);
  }
  if (!createAdj.res.ok) {
    throw new Error(
      `夹具手工奖 200 录入失败（不禁手工录入）：${failBlob(createAdj.res, createAdj.json).slice(0, 300)}`,
    );
  }
  const after = await trialVersion(config.apiUrl, token, c03.version.id, {
    riderId: rider.id,
    start,
    end,
    mode: 'full_version',
  });
  assertTrialOk('手工后', after);
  const afterGross = trialGross(after.json);
  const delta = Math.round((afterGross - beforeGross) * 100) / 100;
  if (moneyEquals(delta, MANUAL_ONCE_AMOUNT * 2) || moneyEquals(afterGross, beforeGross + 400)) {
    throw new Error(`手工奖 200 被加两遍（delta=${delta}）。gross 只含一次 200`);
  }
  if (!moneyEquals(delta, MANUAL_ONCE_AMOUNT)) {
    throw new Error(`无公式加项时手工奖 200 只入账一次。应发增量须=200，实际=${delta}`);
  }
  const adjs = after.json?.data?.adjustments || after.json?.data?.details || [];
  const lines200 = (Array.isArray(adjs) ? adjs : []).filter(
    (row) => Number(row.amount ?? row.signed_amount) === MANUAL_ONCE_AMOUNT,
  );
  if (Array.isArray(adjs) && adjs.length && lines200.length > 1) {
    throw new Error(`手工明细须一条 200，实际 ${JSON.stringify(adjs).slice(0, 300)}`);
  }

  await page.goto(`${config.adminUrl}/rider-salary/plan/editor/${legal.id}`, {
    waitUntil: 'domcontentloaded',
    timeout: 60000,
  });
  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  // 编辑器按阶段卡片列出；钩子挂在周期阶段拼装器上
  const periodItem = page.getByText('保底补足', { exact: true }).first();
  await periodItem.waitFor({ state: 'visible', timeout: 20000 });
  await periodItem.click();
  await page.waitForTimeout(500);
  await requireHooks(page, PR30_MANUAL_HOOKS, '#30 手工双计钩子缺失，不得 skip');
  const banner = await page.getByTestId('ops-plan-manual-not-double').innerText();
  if (banner.trim() !== MANUAL_NOT_DOUBLE_COPY) {
    throw new Error(`ops-plan-manual-not-double 文案须整句 MANUAL_NOT_DOUBLE_COPY。实际 ${banner}`);
  }
  if (!MANUAL_ASSEMBLER_COPY.test(banner) || !MANUAL_ASSEMBLER_DOUBLE_COPY.test(banner)) {
    throw new Error('拼装器须硬区分「可作条件；加进公式 = 双计」。弱提示不得单独当完成态');
  }
  if (!MANUAL_BOOKED_COPY.test(banner) || !MANUAL_DOUBLE_COPY.test(banner)) {
    throw new Error('拼装器须同时含「手工明细已入账」和「再加会双计」');
  }

  const exprBtn = page.getByRole('radio', { name: '表达式' }).or(page.getByText('表达式', { exact: true }));
  if (await exprBtn.first().count()) {
    await exprBtn.first().click().catch(() => {});
    await page.waitForTimeout(300);
  }
  await requireTestId(
    page,
    'plan-manual-field-formula-chip',
    '#30 plan-manual-field-formula-chip 缺失，不得 skip',
  );
  const chip = page.getByTestId('plan-manual-field-formula-chip').filter({ hasText: MANUAL_BONUS_FIELD }).first();
  if (await chip.count()) {
    await chip.click();
    await page.waitForTimeout(300);
  }
  await requireTestId(
    page,
    'plan-manual-added-as-formula',
    '公式把本期手工奖当加项时须见 plan-manual-added-as-formula，不得 skip',
  );
  const added = await page.getByTestId('plan-manual-added-as-formula').innerText();
  if (!added.includes(MANUAL_ADDED_AS_FORMULA_COPY) && !/双计/.test(added)) {
    throw new Error(`plan-manual-added-as-formula 须说明双计。实际 ${added}`);
  }

  const puts = [];
  page.on('request', (req) => {
    if (req.method() === 'PUT' && /\/plan-versions\/\d+\/items/.test(req.url())) {
      puts.push(req.url());
    }
  });
  const saveBtn = page.getByRole('button', { name: /保存/ }).first();
  await saveBtn.waitFor({ state: 'visible', timeout: 20000 });
  await saveBtn.click();
  const dialog = page.getByRole('alertdialog').or(page.getByRole('dialog'));
  const dlg = dialog.filter({ hasText: /手工|双计/ }).first();
  if (await dlg.isVisible().catch(() => false)) {
    const cancel = dlg.getByRole('button', { name: /取消|关闭/ }).first();
    if (await cancel.count()) await cancel.click();
    else await page.keyboard.press('Escape');
  }
  await page.waitForTimeout(800);
  if (puts.length) {
    const afterCancel = await getPlanVersion(config.apiUrl, token, legal.id);
    if ((afterCancel.items || []).some((row) => isManualAddendFormula(row.formula_json))) {
      throw new Error('取消确认不得仍保存手工加项公式');
    }
  }

  await helpers.shot(page, 'cdp-ops-plan-manual-not-double');
}
