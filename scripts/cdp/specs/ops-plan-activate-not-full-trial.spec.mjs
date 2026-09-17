/** CDP: ops-plan-activate-not-full-trial — #27 启用 ≠ 整版试算；挂 trial-equals-calc */
import { apiFetch, siteMonth } from '../cycle1-lib.mjs';
import {
  GOLD_C03_GROSS,
  GOLD_C03_JOB,
  clickStartTrial,
  copyPlanVersion,
  fillTrialTargets,
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
  ACTIVATE_EVERY_SEGMENT_COPY,
  ALLOC_SEGMENT1_BASE,
  BINDING_FULL_AMOUNT_COPY,
  FULL_NOT_BINDING_COPY,
  GREEN_TRIAL_PASSED,
  SEGMENT_FULL_AMOUNT_COPY,
  TWO_SEGMENT_FIXED_GROSS,
  assertActivateNotFullTrial,
  assertLockedGoldUnchanged,
  requireTestId,
} from '../cycle4-lib.mjs';

export const name = 'ops-plan-activate-not-full-trial';

function assertTrialOk(label, trial) {
  if ([404, 405, 501].includes(trial.res.status)) {
    throw new Error(`${label} 试算接口缺失 HTTP ${trial.res.status}，不得 skip`);
  }
  if (!trial.res.ok) {
    throw new Error(`${label} 试算失败 HTTP ${trial.res.status}：${JSON.stringify(trial.json).slice(0, 300)}`);
  }
}

export async function run({ page, helpers, config }) {
  assertLockedGoldUnchanged();
  if (TWO_SEGMENT_FIXED_GROSS !== 4000 || ALLOC_SEGMENT1_BASE !== 933.33) {
    throw new Error('跨段固定额 4000 / 分摊 933.33 合同被改，禁止把 4629.33 拉进金标');
  }
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, siteCode, month } = siteMonth();
  const start = `${month}-01`;
  const end = `${month}-30`;

  const rider = await requireRiderByJobNo(config.apiUrl, token, siteId, GOLD_C03_JOB);
  const c03 = await requireGoldVersion(config.apiUrl, token, 'FIX_C03');
  const full = await trialVersion(config.apiUrl, token, c03.version.id, {
    riderId: rider.id,
    start,
    end,
    mode: 'full_version',
  });
  assertTrialOk('full_version', full);
  if (full.json?.data?.matches_official_calculate === true) {
    throw new Error('整版试算不得打标 matches_official_calculate（不得冒充按当前绑定出账）');
  }
  const binding = await trialVersion(config.apiUrl, token, c03.version.id, {
    riderId: rider.id,
    start,
    end,
    mode: 'binding_segments',
  });
  assertTrialOk('binding_segments', binding);
  if (binding.json?.data?.matches_official_calculate !== true) {
    throw new Error('绑定感知试算须 matches_official_calculate=true。不新造 XOR/金标 Must 名');
  }
  const tGross = trialGross(binding.json);
  if (!Number.isFinite(tGross)) throw new Error('分段试算无应发数字 = FAIL');
  if (moneyEquals(tGross, 4629.33)) throw new Error('不得把 4629.33 拉进金标');

  await page.goto(`${config.adminUrl}/rider-salary/plan`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  const row = page.locator('.vxe-body--row, tr').filter({ hasText: /FIX_C03|底薪 \+ 单量阶梯/ }).first();
  const trialBtn = (await row.count())
    ? row.getByRole('button', { name: /^试算$/ }).first()
    : page.getByRole('button', { name: /^试算$/ }).first();
  await trialBtn.click();
  await page.getByTestId('trial-mode').waitFor({ state: 'visible', timeout: 30000 });

  const fullBtn = page.getByText('整版试算');
  if (await fullBtn.count()) await fullBtn.click();
  await requireTestId(page, 'ops-plan-activate-not-full-trial', '整版模式须见 ops-plan-activate-not-full-trial');
  await requireTestId(page, 'trial-full-not-payroll', '未见 trial-full-not-payroll');
  const fullCopy = await page.getByTestId('trial-full-not-payroll').innerText();
  if (!FULL_NOT_BINDING_COPY.test(fullCopy)) {
    throw new Error(`trial-full-not-payroll 须含「整版试算通过 ≠ 按当前绑定出账」：${fullCopy}`);
  }
  await fillTrialTargets(page, { siteCode, jobNo: GOLD_C03_JOB, start, end });
  await clickStartTrial(page);
  await page.waitForTimeout(600);
  if (await page.getByTestId('trial-matches-official-calculate').isVisible().catch(() => false)) {
    throw new Error('整版试算不得展示 trial-matches-official-calculate 当作出账承诺');
  }

  const bindingBtn = page.getByText('按绑定分段试算');
  if (await bindingBtn.count()) await bindingBtn.click();
  await requireTestId(page, 'trial-binding-fixed-full-amount', '未见 trial-binding-fixed-full-amount');
  const bindCopy = await page.getByTestId('trial-binding-fixed-full-amount').innerText();
  if (!BINDING_FULL_AMOUNT_COPY.test(bindCopy)) {
    throw new Error(`分段须含「每段各计一次全额」：${bindCopy}`);
  }
  await clickStartTrial(page);
  try {
    await page.getByTestId('trial-matches-official-calculate').waitFor({ state: 'visible', timeout: 15000 });
  } catch {
    throw new Error('分段试算须展示 trial-matches-official-calculate（与 trial-equals-calc 同一产品句）');
  }

  await assertActivateNotFullTrial(page);

  const subjects = await listSubjects(config.apiUrl, token);
  const salary = subjectByCode(subjects, 'BASE_SALARY');
  if (!salary) throw new Error('科目 BASE_SALARY 缺失，不得 skip');
  const copied = await copyPlanVersion(config.apiUrl, token, c03.version.id);
  if (!copied?.id) throw new Error('复制草稿失败，无法露出 period-fixed-amount-full-once，不得 skip');
  const put = await putPlanItems(config.apiUrl, token, copied.id, [
    {
      condition_json: {},
      enabled: true,
      formula_json: { 类型: '固定金额', 金额: 2000 },
      name: '底薪',
      sort_order: 10,
      stage: 'period',
      subject_id: salary.id,
    },
  ]);
  if (!put.res.ok) {
    throw new Error(
      `写入周期固定金额草稿失败 HTTP ${put.res.status}，不得 skip：${JSON.stringify(put.json).slice(0, 200)}`,
    );
  }

  await page.goto(`${config.adminUrl}/rider-salary/plan/editor/${copied.id}`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  await requireTestId(page, 'plan-activate-not-full-trial', '编辑器须见 plan-activate-not-full-trial');
  await requireTestId(page, 'plan-trial-label', '编辑器须见 plan-trial-label');
  const label = page.getByTestId('plan-trial-label');
  const labelText = await label.innerText();
  if (GREEN_TRIAL_PASSED.test(labelText) && !FULL_NOT_BINDING_COPY.test(labelText)) {
    throw new Error(`plan-trial-label 不得绿成「试算通过 ✓」冒充出账：${labelText}`);
  }
  const periodItem = page.locator('.vxe-body--row, tr').filter({ hasText: /底薪/ }).first();
  if (await periodItem.count()) await periodItem.click();
  await requireTestId(
    page,
    'period-fixed-amount-full-once',
    '未见 #27 period-fixed-amount-full-once，不得 skip',
  );
  const onceText = await page.getByTestId('period-fixed-amount-full-once').innerText();
  if (!SEGMENT_FULL_AMOUNT_COPY.test(onceText)) {
    throw new Error(`period-fixed-amount-full-once 须含「本段将按全额计一次」：${onceText}`);
  }
  const activate = page.getByTestId('plan-activate-not-full-trial');
  if (await activate.isEnabled()) {
    await activate.click();
    const dlg = page.getByRole('dialog').or(page.getByRole('alertdialog'));
    await dlg.first().waitFor({ state: 'visible', timeout: 10000 }).catch(() => {
      throw new Error('启用确认须弹出，且含整版 ≠ 出账 / 每段各计一次全额。不得 skip');
    });
    const dlgText = await dlg.first().innerText();
    if (!FULL_NOT_BINDING_COPY.test(dlgText) || !ACTIVATE_EVERY_SEGMENT_COPY.test(dlgText)) {
      throw new Error(`启用确认须含整版 ≠ 出账且「每段各计一次全额」：${dlgText}`);
    }
    const cancel = dlg.getByRole('button', { name: /取消|关闭/ }).first();
    if (await cancel.count()) await cancel.click();
    else await page.keyboard.press('Escape');
  }

  const activateRes = await apiFetch(
    config.apiUrl,
    token,
    'POST',
    `/api/v1/rider-salary/plan-versions/${c03.version.id}/activate`,
  );
  if ([404, 405, 501].includes(activateRes.res.status)) {
    throw new Error(`启用接口缺失 HTTP ${activateRes.res.status}，不得 skip`);
  }

  if (!moneyEquals(GOLD_C03_GROSS, 8200)) throw new Error('金标 8200 已锁');
  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-plan-activate-not-full-trial');
}
