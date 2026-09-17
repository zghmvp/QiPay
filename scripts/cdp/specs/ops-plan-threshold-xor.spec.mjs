/** CDP: ops-plan-threshold-xor — 门槛换价条件互斥硬拦 + C08/C05B/C11 金标 */
import {
  activateVersion,
  copyPlanVersion,
  getPlanVersion,
  listSubjects,
  moneyEquals,
  putPlanItems,
  requireGoldVersion,
  requireRiderByJobNo,
  siteMonth,
  trialVersion,
} from '../cycle2-lib.mjs';
import {
  GOLD_C05B_GROSS,
  GOLD_C05B_JOB,
  GOLD_C08_399,
  GOLD_C08_400,
  GOLD_C08_JOB_399,
  GOLD_C08_JOB_400,
  GOLD_C11_GROSS,
  GOLD_C11_JOB,
  XOR_DOUBLE_COPY,
  XOR_FAIL_COPY,
  c08Items,
  trialGross,
} from '../cycle3-lib.mjs';

export const name = 'ops-plan-threshold-xor';

function failBlob(res, json) {
  return `${json?.msg || ''} ${JSON.stringify(json || {})} HTTP ${res.status}`;
}

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();
  const start = `${month}-01`;
  const end = `${month}-30`;
  const subjects = await listSubjects(config.apiUrl, token);

  const c08 = await requireGoldVersion(config.apiUrl, token, 'FIX_C08');
  const rider399 = await requireRiderByJobNo(config.apiUrl, token, siteId, GOLD_C08_JOB_399);
  const rider400 = await requireRiderByJobNo(config.apiUrl, token, siteId, GOLD_C08_JOB_400);
  const t399 = await trialVersion(config.apiUrl, token, c08.version.id, {
    riderId: rider399.id,
    start,
    end,
    mode: 'full_version',
  });
  if ([404, 405, 501].includes(t399.res.status)) {
    throw new Error(`C08 试算缺失 HTTP ${t399.res.status}，不得 skip`);
  }
  if (!t399.res.ok) {
    throw new Error(`C08 399 试算失败：${failBlob(t399.res, t399.json).slice(0, 300)}`);
  }
  const g399 = trialGross(t399.json);
  if (!Number.isFinite(g399)) throw new Error('C08 399 无应发数字 = FAIL');
  if (!moneyEquals(g399, GOLD_C08_399)) {
    throw new Error(`C08 399 单应发须=1995，实际=${g399}（不得写成 399×11 双计）`);
  }
  const t400 = await trialVersion(config.apiUrl, token, c08.version.id, {
    riderId: rider400.id,
    start,
    end,
    mode: 'full_version',
  });
  const g400 = trialGross(t400.json);
  if (!Number.isFinite(g400)) throw new Error('C08 400 无应发数字 = FAIL');
  if (!moneyEquals(g400, GOLD_C08_400)) {
    throw new Error(`C08 400 单应发须=2400，实际=${g400}`);
  }

  const c05 = await requireGoldVersion(config.apiUrl, token, 'FIX_C05');
  const riderB = await requireRiderByJobNo(config.apiUrl, token, siteId, GOLD_C05B_JOB);
  const t05b = await trialVersion(config.apiUrl, token, c05.version.id, {
    riderId: riderB.id,
    start,
    end,
    mode: 'full_version',
  });
  const g05b = trialGross(t05b.json);
  if (!Number.isFinite(g05b)) throw new Error('C05B 无应发数字 = FAIL');
  if (!moneyEquals(g05b, GOLD_C05B_GROSS)) {
    throw new Error(`C05B 1200 单 gross 须=4200（不得仍补到 3500），实际=${g05b}`);
  }

  const c11 = await requireGoldVersion(config.apiUrl, token, 'FIX_C11');
  const rider11 = await requireRiderByJobNo(config.apiUrl, token, siteId, GOLD_C11_JOB);
  const t11 = await trialVersion(config.apiUrl, token, c11.version.id, {
    riderId: rider11.id,
    start,
    end,
    mode: 'full_version',
  });
  const g11 = trialGross(t11.json);
  if (!Number.isFinite(g11)) throw new Error('C11 无应发数字 = FAIL');
  if (!moneyEquals(g11, GOLD_C11_GROSS)) {
    throw new Error(`C11 三阶段同跑 gross 须=4890，实际=${g11}`);
  }

  const copied = await copyPlanVersion(config.apiUrl, token, c08.version.id);
  const overlap = c08Items(subjects, { overlap: true });
  const put = await putPlanItems(config.apiUrl, token, copied.id, overlap);
  const putMsg = failBlob(put.res, put.json);
  if (put.res.ok && (put.json?.code === 200 || put.json?.data)) {
    throw new Error(`门槛两条条件可同时真仍保存成功。须失败并说明互斥否则双计：${putMsg.slice(0, 400)}`);
  }
  if (!XOR_FAIL_COPY.test(putMsg) || !XOR_DOUBLE_COPY.test(putMsg)) {
    throw new Error(`硬拦中文须含「须互斥」和「否则会双计」：${putMsg.slice(0, 400)}`);
  }
  const act = await activateVersion(config.apiUrl, token, copied.id);
  const actMsg = failBlob(act.res, act.json);
  if (act.res.ok && act.json?.code === 200) {
    throw new Error(`重叠条件仍启用成功：${actMsg.slice(0, 300)}`);
  }

  await page.goto(`${config.adminUrl}/rider-salary/plan/editor/${copied.id}`, {
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
  const dialog = page.getByRole('alertdialog').or(page.getByRole('dialog'));
  const dlg = dialog.filter({ hasText: /互斥|双计|门槛/ }).first();
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
    const after = await getPlanVersion(config.apiUrl, token, copied.id);
    const periodItems = (after.items || []).filter((row) => row.stage === 'period');
    const ops = periodItems.map((row) => JSON.stringify(row.condition_json || {}));
    if (ops.some((text) => text.includes('<=') || text.includes('≤')) && puts.length) {
      throw new Error('取消确认后仍保存了不互斥的门槛换价项');
    }
  }

  await helpers.shot(page, 'cdp-ops-plan-threshold-xor');
}
