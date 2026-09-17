/** CDP: ops-dashboard-no-plan-to-binding — 无方案日行落到档案绑定时间轴 */
import { FIX_JOB_NO } from '../cycle1-lib.mjs';
import {
  BINDING_CREATE_COPY,
  BINDING_TAB_COPY,
  EMPTY_CALENDAR_COPY,
  assertLockedGoldUnchanged,
  assertRowGoesToBinding,
  assertViewAllNotEmptyCalendar,
  fetchDashboardSummary,
  isCalendarPath,
  requireStatusHooks,
  waitPath,
} from '../cycle5-lib.mjs';

export const name = 'ops-dashboard-no-plan-to-binding';

export async function run({ page, helpers, config }) {
  assertLockedGoldUnchanged();
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const siteId = process.env.CDP_SITE_ID || '13';
  const month = process.env.CDP_MONTH || '2026-09';
  const summary = await fetchDashboardSummary(config.apiUrl, admin.access_token, { siteId, month });
  const block = (summary?.attention || []).find((row) => row.key === 'no_plan_days');
  if (!block || !block.count) {
    throw new Error(
      `工作台无无方案日（#9 live 谓词须仍出现）。请确认 ${FIX_JOB_NO} 有完成单无绑定。不得 skip`,
    );
  }
  const item = (block.items || []).find((row) => row.job_no === FIX_JOB_NO) || block.items?.[0];
  if (!item?.rider_id) throw new Error('无方案日行缺少 rider_id，不得 skip');

  const gap = (summary?.attention || []).find((row) => row.key === 'import_gaps');
  if (gap?.link && String(gap.link).includes('/calendar') && !String(gap.link).includes('rider_id')) {
    throw new Error(`导入缺口查看全部不得回退成空日历：${gap.link}`);
  }

  await page.goto(
    `${config.adminUrl}/rider-salary/dashboard?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  const body = await page.locator('body').innerText();
  if (!body.includes('无方案日')) throw new Error('工作台未见「无方案日」，不得 skip');
  helpers.assertNoPaymentTaxCopy(body);

  const panel = page.locator('.ant-collapse-panel, [data-testid]').filter({ hasText: '无方案日' }).first();
  await panel.waitFor({ state: 'visible', timeout: 20000 });
  const row = panel.locator('tr, .vxe-body--row').filter({
    hasText: new RegExp(item.job_no || item.name || '.'),
  }).first();
  if (!(await row.count())) {
    throw new Error(`未见无方案日行 ${item.job_no || item.name}，不得 skip`);
  }
  await row.click();
  await page.waitForTimeout(500);
  if (isCalendarPath(page.url())) {
    throw new Error(`点行只进 /calendar = FAIL（即使带 rider_id+site_id+month）。实际 ${page.url()}`);
  }
  const landed = await waitPath(page, /\/rider-salary\/rider/, 20000);
  assertRowGoesToBinding(landed, item.rider_id);
  await page.waitForTimeout(400);
  if (/\/rider-salary\/rider\?/.test(page.url()) && page.url().includes('tab=binding')) {
    await waitPath(page, /\/rider-salary\/rider\/\d+/, 15000);
  }
  const profileUrl = page.url();
  assertRowGoesToBinding(profileUrl, item.rider_id);
  const profile = await page.locator('body').innerText();
  if (!BINDING_TAB_COPY.test(profile)) {
    throw new Error(`须可见绑定时间轴（方案绑定）。实际 ${profileUrl}`);
  }
  if (!BINDING_CREATE_COPY.test(profile)) {
    throw new Error('绑定页须可新建/改绑定（新增绑定或保存绑定）。带参日历不够绿');
  }
  const gotoCalc = page.getByTestId('rider-binding-goto-calculate');
  if (!(await gotoCalc.count())) {
    throw new Error('绑定时间轴须仍见 rider-binding-goto-calculate（#9/#7 回归，不得 skip）');
  }

  await page.goto(
    `${config.adminUrl}/rider-salary/dashboard?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  const again = page.locator('.ant-collapse-panel, [data-testid]').filter({ hasText: '无方案日' }).first();
  await again.waitFor({ state: 'visible', timeout: 20000 });
  const viewAll = again.getByRole('button', { name: '查看全部' }).or(again.getByText('查看全部'));
  await viewAll.first().click();
  await page.waitForTimeout(800);
  const viewUrl = page.url();
  const viewBody = await page.locator('body').innerText();
  if (EMPTY_CALENDAR_COPY.test(viewBody)) {
    throw new Error(`查看全部落到「请选择站点和骑手」空日历 = FAIL。实际 ${viewUrl}`);
  }
  assertViewAllNotEmptyCalendar(viewUrl, viewBody);

  await page.goto(
    `${config.adminUrl}/rider-salary/calendar?site_id=${siteId}&rider_id=${item.rider_id}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  const bind = page.getByTestId('calendar-bind-plan');
  if (!(await bind.count())) {
    throw new Error('#7 日历格「去绑」回归须继续绿：未见 calendar-bind-plan，不得 skip');
  }

  await page.goto(
    `${config.adminUrl}/rider-salary/dashboard?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  await requireStatusHooks(page, 'status 已落地的无方案日绑定钩子缺失，不得 skip');
  await helpers.shot(page, 'cdp-ops-dashboard-no-plan-to-binding');
}
