/** CDP: ops-lock-reason-matches-calc — 锁账失败理由与算薪同口径（PR #16 硬失败先于 stale） */
import {
  FIX_JOB_NO,
  HARD_FAIL_COPY,
  STALE_COPY,
  STILL_LOCK_COPY,
  apiFetch,
  assertNoStillLock,
  clickPeriodLock,
  lockErrorLocator,
  siteLevelOpenPeriod,
  siteMonth,
  submitLockReasonIfAsked,
} from '../cycle1-lib.mjs';

export const name = 'ops-lock-reason-matches-calc';

function assertHardFailBeforeStale(msg, where) {
  if (STILL_LOCK_COPY.test(msg)) {
    throw new Error(`${where} 禁止「仍要锁」：${msg.slice(0, 300)}`);
  }
  if (STALE_COPY.test(msg) && !HARD_FAIL_COPY.test(msg)) {
    throw new Error(
      `${where} 只用 stale「请先重算」结束，硬失败被盖住（PR #16 / 计划 Must 4）：${msg.slice(0, 400)}`,
    );
  }
  if (!HARD_FAIL_COPY.test(msg)) {
    throw new Error(`${where} 缺少与算薪同口径硬拦句：${msg.slice(0, 400)}`);
  }
  const hardAt = msg.search(/锁账中止|无生效方案|未算出|缺送达|送达时间为空|从未成功/);
  const staleAt = msg.search(/存在需重算的薪资结果|请先重算/);
  if (staleAt >= 0 && hardAt >= 0 && hardAt > staleAt) {
    throw new Error(`${where} 硬失败须出现在 stale「请先重算」之前：${msg.slice(0, 400)}`);
  }
}

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();
  const period = await siteLevelOpenPeriod({
    apiUrl: config.apiUrl,
    token,
    siteId,
    month,
  });
  if (!period?.id) {
    throw new Error('未找到站点月开放周期（本 spec 不锁 FIX_C17_LOCK 隔离岛）');
  }

  const lockRes = await fetch(
    `${config.apiUrl}/api/v1/rider-salary/periods/${period.id}/lock`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ reason: 'CDP 锁账同口径' }),
    },
  );
  const lockJson = await lockRes.json().catch(() => ({}));
  const msg = `${lockJson?.msg || ''} ${JSON.stringify(lockJson?.data || {})}`;
  if (lockRes.ok && lockJson?.code === 200) {
    throw new Error(`站点月周期 ${period.id} 在 ${FIX_JOB_NO} 无方案有单时不应锁成功`);
  }
  assertHardFailBeforeStale(msg, '锁账 API');

  const after = await apiFetch(
    config.apiUrl,
    token,
    'GET',
    `/api/v1/rider-salary/periods/${period.id}`,
  );
  const status = after.json?.data?.status;
  if (status === 'locked' || status === 'paid') {
    throw new Error(`锁账被拒绝后状态仍变为 ${status}`);
  }

  await page.goto(
    `${config.adminUrl}/rider-salary/period?site_id=${siteId}&month=${month}&id=${period.id}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  await clickPeriodLock(page, period);
  await submitLockReasonIfAsked(page);
  const err = lockErrorLocator(page);
  await err.waitFor({ state: 'visible', timeout: 20000 });
  const errText = await err.innerText();
  assertNoStillLock(errText);
  assertHardFailBeforeStale(errText, '#period-lock-error');
  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-lock-reason-matches-calc');
}
