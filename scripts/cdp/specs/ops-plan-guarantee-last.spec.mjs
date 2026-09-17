/** CDP: ops-plan-guarantee-last — 保底非周期末位保存/启用失败；取消不得仍保存 */
import {
  GUARANTEE_FAIL_COPY,
  activateVersion,
  c05Items,
  copyPlanVersion,
  getPlanVersion,
  listSubjects,
  putPlanItems,
  requireGoldVersion,
  siteMonth,
} from '../cycle2-lib.mjs';

export const name = 'ops-plan-guarantee-last';

function failBlob(res, json) {
  return `${json?.msg || ''} ${JSON.stringify(json || {})} HTTP ${res.status}`;
}

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const subjects = await listSubjects(config.apiUrl, token);
  const { version } = await requireGoldVersion(config.apiUrl, token, 'FIX_C05');
  const copied = await copyPlanVersion(config.apiUrl, token, version.id);
  const draftId = copied.id;
  const misplaced = c05Items(subjects, { guaranteeLast: false });

  const put = await putPlanItems(config.apiUrl, token, draftId, misplaced);
  const putMsg = failBlob(put.res, put.json);
  if (put.res.ok && (put.json?.code === 200 || put.json?.data)) {
    throw new Error(
      `保底非周期末位仍保存成功。保存须失败且中文含「须放在周期阶段最后」：${putMsg.slice(0, 400)}`,
    );
  }
  if (!GUARANTEE_FAIL_COPY.test(putMsg)) {
    throw new Error(`保底硬拦文案须含「须放在周期阶段最后」或「须沉底」：${putMsg.slice(0, 400)}`);
  }

  const act = await activateVersion(config.apiUrl, token, draftId);
  const actMsg = failBlob(act.res, act.json);
  if (act.res.ok && act.json?.code === 200) {
    throw new Error(`保底非末位仍启用成功：${actMsg.slice(0, 300)}`);
  }
  if (!GUARANTEE_FAIL_COPY.test(actMsg) && act.res.ok) {
    throw new Error(`启用须失败并说明须沉底：${actMsg.slice(0, 300)}`);
  }

  await page.goto(`${config.adminUrl}/rider-salary/plan/editor/${draftId}`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());

  const puts = [];
  page.on('request', (req) => {
    if (req.method() === 'PUT' && /\/plan-versions\/\d+\/items/.test(req.url())) {
      puts.push(req.url());
    }
  });
  const saveBtn = page.getByRole('button', { name: /保存/ }).first();
  await saveBtn.waitFor({ state: 'visible', timeout: 20000 });
  await saveBtn.click();

  const dialog = page.getByRole('alertdialog').or(page.getByRole('dialog')).or(
    page.locator('[data-slot="alert-dialog-content"], [data-slot="dialog-content"]'),
  );
  const dlg = dialog.filter({ hasText: /保底|沉底|本期已计金额/ }).first();
  if (await dlg.isVisible().catch(() => false)) {
    const cancel = dlg.getByRole('button', { name: /取消|关闭/ }).first();
    if (await cancel.count()) {
      await cancel.click();
    } else {
      await page.keyboard.press('Escape');
    }
  }
  await page.waitForTimeout(800);
  if (puts.length) {
    const after = await getPlanVersion(config.apiUrl, token, draftId);
    const period = (after.items || []).filter((row) => row.stage === 'period' && row.enabled !== false);
    const last = period[period.length - 1];
    const guarantee = period.find((row) => /保底|补足|本期已计金额/.test(`${row.name}${JSON.stringify(row.formula_json || {})}`));
    if (guarantee && last && guarantee.id !== last.id && guarantee.sort_order < last.sort_order) {
      throw new Error('取消确认后仍保存了保底非末位顺序（弱提示假完成）');
    }
  }

  const body = await page.locator('body').innerText();
  if (/不强制拦截|取消则按当前顺序保存/.test(body) && !GUARANTEE_FAIL_COPY.test(body)) {
    throw new Error('编辑器仍是「取消仍保存」弱提示，Cycle 2 须硬拦');
  }
  void siteMonth;
  await helpers.shot(page, 'cdp-ops-plan-guarantee-last');
}
