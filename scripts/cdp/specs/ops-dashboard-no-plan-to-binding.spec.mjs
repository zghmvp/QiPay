/** CDP: ops-dashboard-no-plan-to-binding — 无方案日行落到档案绑定时间轴（#30 钩子；Must 2 无 BE） */
import { FIX_JOB_NO } from '../cycle1-lib.mjs';
import {
  BINDING_CREATE_COPY,
  BINDING_TAB_COPY,
  EMPTY_CALENDAR_COPY,
  NO_PLAN_LIST_COPY,
  PR30_BINDING_HOOKS,
  PR30_BINDING_LANDING_HOOKS,
  assertLockedGoldUnchanged,
  assertRowGoesToBinding,
  assertViewAllNotEmptyCalendar,
  fetchDashboardSummary,
  isCalendarPath,
  requireHooks,
  requireTestId,
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
    { waitUntil: 'domcontentloaded', timeout: 60000 },
  );
  await requireTestId(
    page,
    'ops-dashboard-no-plan-to-binding',
    '工作台未见无方案日块（#30），不得 skip',
  );
  const body = await page.locator('body').innerText();
  if (!body.includes('无方案日')) throw new Error('工作台未见「无方案日」，不得 skip');
  helpers.assertNoPaymentTaxCopy(body);

  // a-collapse 默认折叠；行/查看全部在 panel 体内
  await page.getByTestId('ops-dashboard-no-plan-to-binding').first().click();
  await requireHooks(page, PR30_BINDING_HOOKS, '#30 无方案日绑定钩子缺失，不得 skip');
  const row = page.getByTestId('dashboard-no-plan-row').filter({
    hasText: new RegExp(item.job_no || item.name || '.'),
  }).first();
  if (!(await row.count())) {
    throw new Error(`未见 dashboard-no-plan-row ${item.job_no || item.name}，不得 skip`);
  }
  await row.click();
  await page.waitForTimeout(500);
  if (isCalendarPath(page.url())) {
    throw new Error(`点行只进 /calendar = FAIL（即使带 rider_id+site_id+month）。实际 ${page.url()}`);
  }
  const landed = await waitPath(page, /\/rider-salary\/rider\/\d+/, 20000);
  assertRowGoesToBinding(landed, item.rider_id);
  await requireHooks(page, PR30_BINDING_LANDING_HOOKS, '#30 绑定时间轴钩子缺失，不得 skip');
  const profile = await page.locator('body').innerText();
  if (!BINDING_TAB_COPY.test(profile)) {
    throw new Error(`须可见绑定时间轴（方案绑定）。实际 ${page.url()}`);
  }
  if (!BINDING_CREATE_COPY.test(profile)) {
    throw new Error('绑定页须可新建/改绑定（新增绑定或保存绑定）。带参日历不够绿');
  }

  await page.goto(
    `${config.adminUrl}/rider-salary/dashboard?site_id=${siteId}&month=${month}`,
    { waitUntil: 'domcontentloaded', timeout: 60000 },
  );
  await requireTestId(page, 'ops-dashboard-no-plan-to-binding', '返回工作台未见无方案日块');
  await page.getByTestId('ops-dashboard-no-plan-to-binding').first().click();
  await requireTestId(page, 'dashboard-no-plan-view-all', '#30 dashboard-no-plan-view-all 缺失，不得 skip');
  await page.getByTestId('dashboard-no-plan-view-all').click();
  await page.waitForTimeout(800);
  const viewUrl = page.url();
  const viewBody = await page.locator('body').innerText();
  if (EMPTY_CALENDAR_COPY.test(viewBody) || isCalendarPath(viewUrl)) {
    throw new Error(`查看全部落到日历 / 「请选择站点和骑手」= FAIL。实际 ${viewUrl}`);
  }
  assertViewAllNotEmptyCalendar(viewUrl, viewBody);
  await requireTestId(page, 'rider-list-no-plan-scope', '#30 rider-list-no-plan-scope 缺失，不得 skip');
  if (!NO_PLAN_LIST_COPY.test(viewBody) && !viewBody.includes('方案绑定')) {
    throw new Error('落地须含「方案绑定」且「不要只打开日历」');
  }

  await page.goto(
    `${config.adminUrl}/rider-salary/calendar?site_id=${siteId}&rider_id=${item.rider_id}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  await requireTestId(page, 'calendar-bind-plan', '#7 日历格「去绑」回归须继续绿：未见 calendar-bind-plan，不得 skip');

  await helpers.shot(page, 'cdp-ops-dashboard-no-plan-to-binding');
}
