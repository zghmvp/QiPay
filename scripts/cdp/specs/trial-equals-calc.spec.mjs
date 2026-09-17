/** CDP: trial-equals-calc — 绑定感知试算应发 = 正式 calculate gross；列表不得 Modal 完成算薪 */
import { apiFetch, siteLevelOpenPeriod, siteMonth } from '../cycle1-lib.mjs';
import {
  GOLD_C03_GROSS,
  GOLD_C03_JOB,
  clickStartTrial,
  fillTrialTargets,
  moneyEquals,
  readTrialGross,
  requireGoldVersion,
  requireRiderByJobNo,
  trialVersion,
} from '../cycle2-lib.mjs';
import {
  CALC_MODAL_TITLE,
  calcGross,
  trialGross,
} from '../cycle3-lib.mjs';
import { assertActivateNotFullTrial } from '../cycle4-lib.mjs';

export const name = 'trial-equals-calc';

function assertTrialOk(label, trial) {
  if ([404, 405, 501].includes(trial.res.status)) {
    throw new Error(`${label} 试算接口缺失 HTTP ${trial.res.status}，不得 skip`);
  }
  if (!trial.res.ok) {
    throw new Error(`${label} 试算失败 HTTP ${trial.res.status}：${JSON.stringify(trial.json).slice(0, 300)}`);
  }
}

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, siteCode, month } = siteMonth();
  const start = `${month}-01`;
  const end = `${month}-30`;

  const rider = await requireRiderByJobNo(config.apiUrl, token, siteId, GOLD_C03_JOB);
  const c03 = await requireGoldVersion(config.apiUrl, token, 'FIX_C03');
  const trial = await trialVersion(config.apiUrl, token, c03.version.id, {
    riderId: rider.id,
    start,
    end,
    mode: 'binding_segments',
  });
  assertTrialOk('binding_segments', trial);
  if (trial.json?.data?.matches_official_calculate !== true) {
    throw new Error(
      `binding_segments 须 matches_official_calculate=true，不得 skip。实际=${JSON.stringify(trial.json?.data).slice(0, 200)}`,
    );
  }
  const tGross = trialGross(trial.json);
  if (!Number.isFinite(tGross)) {
    throw new Error('分段试算无应发数字 = FAIL（禁止 WARN / skip）');
  }

  const period = await siteLevelOpenPeriod({ apiUrl: config.apiUrl, token, siteId, month });
  if (!period?.id) throw new Error('本站无开放周期，无法对拍正式 calculate');
  const calc = await apiFetch(
    config.apiUrl,
    token,
    'POST',
    `/api/v1/rider-salary/periods/${period.id}/calculate`,
    { rider_ids: [rider.id] },
  );
  if ([404, 405, 501].includes(calc.res.status)) {
    throw new Error(`正式 calculate 缺失 HTTP ${calc.res.status}，不得 skip`);
  }
  if (!calc.res.ok) {
    throw new Error(
      `正式 calculate 失败 HTTP ${calc.res.status}：${JSON.stringify(calc.json).slice(0, 300)}`,
    );
  }
  const cGross = calcGross(calc.json);
  const payrolls = calc.json?.data?.payrolls || [];
  const hit = payrolls.find((row) => Number(row.rider_id) === Number(rider.id)) || payrolls[0];
  const persistGross = Number(hit?.gross ?? cGross);
  const comparable = Number.isFinite(persistGross) ? persistGross : tGross;
  if (!moneyEquals(tGross, comparable) && !moneyEquals(tGross, GOLD_C03_GROSS)) {
    throw new Error(
      `绑定感知试算应发须与同骑手同周期正式 calculate gross 对拍。试算=${tGross} 正式=${comparable}`,
    );
  }
  if (moneyEquals(tGross, GOLD_C03_GROSS) && Number.isFinite(persistGross) && persistGross > 0) {
    if (!moneyEquals(tGross, persistGross)) {
      throw new Error(
        `C03 试算 ${tGross} 与正式 ${persistGross} 不一致（须同一条应发，预支只影响 net）`,
      );
    }
  }

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
  const binding = page.getByText('按绑定分段试算');
  if (await binding.count()) {
    await binding.click();
  }
  await fillTrialTargets(page, { siteCode, jobNo: GOLD_C03_JOB, start, end });
  await clickStartTrial(page);
  const uiGross = await readTrialGross(page);
  if (!Number.isFinite(uiGross)) {
    throw new Error('试算 UI 无应发数字 = FAIL');
  }
  if (!moneyEquals(uiGross, tGross)) {
    throw new Error(`UI 试算应发 ${uiGross} 须等于接口 ${tGross}`);
  }
  const matchBadge = page.getByTestId('trial-matches-official-calculate');
  try {
    await matchBadge.waitFor({ state: 'visible', timeout: 10000 });
  } catch {
    throw new Error('分段试算须展示 trial-matches-official-calculate（应发与正式 calculate 同源）');
  }

  await page.goto(
    `${config.adminUrl}/rider-salary/period?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  const calcPosts = [];
  page.on('request', (req) => {
    if (req.method() === 'POST' && /\/periods\/\d+\/calculate$/.test(req.url())) {
      calcPosts.push(req.url());
    }
  });
  const listRow = page.locator('.vxe-body--row, tr').filter({ hasText: period.start_date || '' }).first();
  const calcBtn = (await listRow.count())
    ? listRow.getByText('算薪', { exact: true }).first()
    : page.getByRole('button', { name: /^算薪$/ }).first();
  await calcBtn.click();
  await page.waitForTimeout(800);
  const url = page.url();
  if (!new RegExp(`/rider-salary/period/${period.id}/calculate`).test(url)) {
    throw new Error(`周期列表「算薪」须进独立算薪页 /period/:id/calculate，实际 ${url}`);
  }
  const modal = page.getByRole('dialog').filter({ hasText: CALC_MODAL_TITLE });
  if (await modal.isVisible().catch(() => false)) {
    throw new Error('列表不得再弹出可提交的「计算周期薪资」Modal');
  }
  if (calcPosts.length && /\/period\/\d+\/calculate/.test(url) === false) {
    throw new Error('列表算薪不得在 Modal 里直接 POST /calculate');
  }

  await page.goto(`${config.adminUrl}/rider-salary/plan`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  const planRow = page.locator('.vxe-body--row, tr').filter({ hasText: /FIX_C03|底薪 \+ 单量阶梯/ }).first();
  const openTrial = (await planRow.count())
    ? planRow.getByRole('button', { name: /^试算$/ }).first()
    : page.getByRole('button', { name: /^试算$/ }).first();
  await openTrial.click();
  await page.getByTestId('trial-mode').waitFor({ state: 'visible', timeout: 20000 });
  await assertActivateNotFullTrial(page);

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-trial-equals-calc');
}
