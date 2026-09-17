/** CDP: ops-trial-period-vs-plan-order-count — 试算摘要同时给出两个中文单量 */
import {
  GOLD_C17_PERIOD_AMOUNT,
  GOLD_C17_PLAN_AMOUNT,
  LOCKED_GOLD_FORBIDDEN,
  MUST4_HOOKS,
  PERIOD_VALID_LABEL,
  PLAN_PERIOD_LABEL,
  assertLockedGoldUnchanged,
  requireHooks,
  requireTestId,
  siteMonth,
  trialOrderCounts,
  trialVersion,
} from '../cycle13-lib.mjs';

export const name = 'ops-trial-period-vs-plan-order-count';

export async function run({ page, helpers, config }) {
  assertLockedGoldUnchanged();
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, siteCode, month } = siteMonth();
  const versionId = process.env.CDP_TRIAL_VERSION_ID;
  const riderId = process.env.CDP_REBIND_RIDER_ID || process.env.CDP_RIDER_ID;
  if (!versionId || !riderId) {
    throw new Error(
      '换绑夹具须 CDP_TRIAL_VERSION_ID + CDP_REBIND_RIDER_ID。只一张「单量」卡 / 两数永远相等且无字段名 = FAIL，不得 skip',
    );
  }

  const trial = await trialVersion(config.apiUrl, token, versionId, {
    riderId,
    start: `${month}-01`,
    end: `${month}-30`,
  });
  if ([404, 405, 501].includes(trial.res.status)) {
    throw new Error(`试算接口缺失 HTTP ${trial.res.status}，不得 skip`);
  }
  if (!trial.res.ok) {
    throw new Error(`试算失败 HTTP ${trial.res.status}：${JSON.stringify(trial.json).slice(0, 300)}`);
  }
  const counts = trialOrderCounts(trial.json);
  if (!Number.isFinite(counts.periodValid) || !Number.isFinite(counts.planPeriod)) {
    throw new Error(
      '摘要须同时给出周期有效单量与方案期内单量。对照只在 calc_trace JSON = FAIL',
    );
  }
  if (counts.periodValid === counts.planPeriod) {
    throw new Error(
      `月中换绑夹具上两数必须能分叉。永远相等且无字段名 = FAIL。周期有效=${counts.periodValid} 方案期内=${counts.planPeriod}`,
    );
  }

  await page.goto(`${config.adminUrl}/rider-salary/plan`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  const trialBtn = page.getByRole('button', { name: /^试算$/ }).first();
  await trialBtn.click();
  await page.getByTestId('ops-trial-period-vs-plan-order-count').or(page.getByText('开始试算')).first().waitFor({
    state: 'visible',
    timeout: 30000,
  });

  const siteBox = page.locator('.ant-select').first();
  if (await siteBox.count()) {
    await siteBox.click();
    await page.locator('.ant-select-item-option').filter({ hasText: new RegExp(siteCode) }).first().click().catch(() => {});
  }

  await page.getByRole('button', { name: /开始试算/ }).click().catch(() => {});
  await requireHooks(
    page,
    MUST4_HOOKS,
    '未见 ops-trial-period-vs-plan-order-count / trial-valid-order-count / trial-plan-order-count。只一张「单量」卡 = FAIL，不得 skip',
  );
  const panel = page.getByTestId('ops-trial-period-vs-plan-order-count').first();
  const panelText = await panel.innerText();
  if (!panelText.includes(PERIOD_VALID_LABEL) || !panelText.includes(PLAN_PERIOD_LABEL)) {
    throw new Error(`摘要须同时给出「${PERIOD_VALID_LABEL}」与「${PLAN_PERIOD_LABEL}」。实际：${panelText.slice(0, 200)}`);
  }
  const validText = await page.getByTestId('trial-valid-order-count').innerText();
  const planText = await page.getByTestId('trial-plan-order-count').innerText();
  if (!/\d/.test(validText) || !/\d/.test(planText)) {
    throw new Error('两张命名单量卡须有数字。对照只在轨迹 JSON = FAIL');
  }
  if (validText.trim() === planText.trim() && counts.periodValid === counts.planPeriod) {
    throw new Error('换绑夹具两数必须分叉。永远相等 = FAIL');
  }
  if (LOCKED_GOLD_FORBIDDEN.test(panelText)) {
    throw new Error('禁止借此改 8200 / 7800 / 3500');
  }
  if (
    GOLD_C17_PERIOD_AMOUNT !== 2310 ||
    GOLD_C17_PLAN_AMOUNT !== 100
  ) {
    throw new Error('C17 仍走已锁 420→2310 / 20→100，不得新开案例号');
  }

  await requireTestId(page, 'trial-valid-order-count', '周期有效单量卡缺失');
  await requireTestId(page, 'trial-plan-order-count', '方案期内单量卡缺失');
  void siteId;

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-trial-period-vs-plan-order-count');
}
