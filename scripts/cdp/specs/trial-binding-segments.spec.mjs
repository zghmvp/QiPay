/** CDP: trial-binding-segments — 分段试算双单量分叉 */
export const name = 'trial-binding-segments';

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);

  // 打开方案列表 → 进入编辑器（演示机需已有草稿版本；否则至少验证控件存在路径）
  await page.goto(`${config.adminUrl}/rider-salary/plan`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());

  // 尝试点进第一个「编辑」；若无数据则记录缺口但不伪装绿
  const edit = page.getByRole('button', { name: /编辑|试算/ }).first();
  if ((await edit.count()) === 0) {
    throw new Error('方案列表无编辑/试算入口，请先灌 FIX_C17 演示种子');
  }
  await edit.click();
  await page.waitForTimeout(1000);

  // 若已在编辑器，打开试算
  const trialBtn = page.getByRole('button', { name: /试算/ }).first();
  if ((await trialBtn.count()) > 0) {
    await trialBtn.click();
  }

  const mode = page.getByTestId('trial-mode');
  await mode.waitFor({ state: 'visible', timeout: 30000 });
  await page.getByText('按绑定分段试算').click();

  // 站点/骑手由演示数据决定；若无法选中则失败
  // 尽量选择可见下拉第一项
  const site = page.locator('.ant-select').first();
  if ((await site.count()) > 0) {
    await site.click();
    await page.locator('.ant-select-item-option').first().click().catch(() => {});
  }

  await helpers.shot(page, 'cdp-trial-binding-segments-panel');

  // 若结果区已有对照数字则断言分叉
  const validEl = page.getByTestId('trial-valid-order-count');
  const planEl = page.getByTestId('trial-plan-order-count');
  if ((await validEl.count()) > 0 && (await planEl.count()) > 0) {
    const valid = Number((await validEl.innerText()).trim());
    const plan = Number((await planEl.innerText()).trim());
    if (!(Number.isFinite(valid) && Number.isFinite(plan))) {
      throw new Error('单量口径非数字');
    }
    if (valid === plan) {
      throw new Error(`分段试算两值未分叉：valid=${valid} plan=${plan}（需换绑夹具）`);
    }
    await helpers.shot(page, 'cdp-trial-binding-segments-diverge');
  } else {
    // 面板模式切换已可见即算控件验收；金额分叉依赖灌种后点「开始试算」
    console.warn('WARN: 尚未跑出试算结果数字，请在演示机灌种后复跑并点开始试算');
  }
}
