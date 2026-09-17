/** CDP: ops-queued-calc-progress — queued 可见排队中/计算中 + 刷新；阈值替身；failed>0 不纯绿 */
import { GREEN_COMPLETE_COPY, siteLevelOpenPeriod, siteMonth } from '../cycle1-lib.mjs';
import { QUEUED_COPY, REFRESH_COPY } from '../cycle2-lib.mjs';

export const name = 'ops-queued-calc-progress';

const QUEUED_STUB = {
  code: 200,
  msg: '成功',
  data: {
    calculated: 0,
    failed: [],
    queued: true,
    warnings: ['骑手数超过阈值，已转入后台计算'],
  },
};

const FAILED_STUB = {
  code: 200,
  msg: '成功',
  data: {
    calculated: 1,
    queued: false,
    failed: [{ rider_id: 9, job_no: 'FIX_C17_R1', rider_name: '换绑夹具骑手', errors: ['无生效方案'] }],
    warnings: [],
  },
};

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();
  const period = await siteLevelOpenPeriod({ apiUrl: config.apiUrl, token, siteId, month });
  if (!period?.id) throw new Error('本站无开放周期');

  const threshold = Number(process.env.CDP_QUEUED_RIDER_THRESHOLD || '2');
  let usedLiveQueued = false;

  await page.route('**/api/v1/rider-salary/periods/*/calculate', async (route) => {
    if (route.request().method() !== 'POST') {
      await route.continue();
      return;
    }
    if (!usedLiveQueued) {
      usedLiveQueued = true;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(QUEUED_STUB),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(FAILED_STUB),
    });
  });

  await page.goto(`${config.adminUrl}/rider-salary/period/${period.id}/calculate`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });

  const start = page.getByTestId('period-calc-start');
  if (await start.isEnabled().catch(() => false)) {
    await start.click();
  } else {
    await page.evaluate(() => {
      const btn = document.querySelector('[data-testid="period-calc-start"]');
      if (btn) btn.click();
    });
  }

  const queuedBox = page.getByTestId('period-calc-queued');
  try {
    await queuedBox.first().waitFor({ state: 'visible', timeout: 20000 });
  } catch {
    throw new Error('queued=true 后须见 period-calc-queued，不得只剩一条消失的 toast');
  }
  const queuedText = await queuedBox.first().innerText();
  if (!QUEUED_COPY.test(queuedText)) {
    throw new Error(`period-calc-queued 须含「排队中/计算中」：${queuedText}`);
  }
  const refresh = page.getByTestId('period-calc-refresh');
  try {
    await refresh.waitFor({ state: 'visible', timeout: 15000 });
  } catch {
    throw new Error('须有 period-calc-refresh「刷新预检/结果」。没有刷新控件 = FAIL。不要进度条/Celery/任务中心');
  }
  const refreshText = await refresh.innerText();
  if (!REFRESH_COPY.test(refreshText)) {
    throw new Error(`period-calc-refresh 文案须为「刷新预检/结果」：${refreshText}`);
  }
  await helpers.shot(page, 'cdp-ops-queued-calc-progress-queued');

  await refresh.click();
  await page.waitForTimeout(500);

  if (await start.isEnabled().catch(() => false)) {
    await start.click();
  }
  const after = await page.locator('body').innerText();
  if (GREEN_COMPLETE_COPY.test(after) && /失败/.test(after) === false && /FIX_C17_R1|无生效方案/.test(after)) {
    throw new Error('failed>0 仍禁止纯绿「完成」');
  }
  if (/完成/.test(after) && /失败/.test(FAILED_STUB.data.failed[0].errors[0]) === false) {
    if (/已计算\s*1\s*名/.test(after) && !/失败/.test(after)) {
      throw new Error('部分失败不得纯绿完成');
    }
  }
  if (/进度条|任务中心|Celery/.test(after)) {
    throw new Error('queued 薄进度不得做成进度条/任务中心');
  }
  helpers.assertNoPaymentTaxCopy(after);
  void threshold;
  await helpers.shot(page, 'cdp-ops-queued-calc-progress');
}
