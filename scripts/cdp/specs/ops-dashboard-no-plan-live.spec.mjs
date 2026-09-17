/** CDP: ops-dashboard-no-plan-live — 工作台无方案日 live，导入缺口不是空日历 */
export const name = 'ops-dashboard-no-plan-live';

const FIX_JOB_NO = 'FIX_C17_R1';

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const siteId = process.env.CDP_SITE_ID || '13';
  const month = process.env.CDP_MONTH || '2026-09';
  const headers = { Authorization: `Bearer ${admin.access_token}` };

  const dash = await fetch(
    `${config.apiUrl}/api/v1/rider-salary/dashboard/summary?site_id=${siteId}&month=${month}`,
    { headers },
  );
  if (!dash.ok) throw new Error(`工作台摘要失败 ${dash.status}`);
  const summary = (await dash.json())?.data;
  const block = (summary?.attention || []).find((row) => row.key === 'no_plan_days');
  if (!block || !block.count) {
    throw new Error(
      `工作台无无方案日（live）。请确认 ${FIX_JOB_NO} 9/15–17 有完成单无绑定。`,
    );
  }
  const item = (block.items || []).find((row) => row.job_no === FIX_JOB_NO) || block.items?.[0];
  if (!item) throw new Error('无方案日行缺少条目');
  if (!item.site_id || !item.rider_id) {
    throw new Error(`无方案日行未带站点/骑手：${JSON.stringify(item)}`);
  }
  if (!String(block.link || '').includes('site_id') || !String(block.link || '').includes('month')) {
    throw new Error(`无方案日查看全部未带 site/month：${block.link}`);
  }

  const gap = (summary?.attention || []).find((row) => row.key === 'import_gaps');
  if (gap?.link) {
    if (String(gap.link).includes('/calendar') && !String(gap.link).includes('rider_id')) {
      throw new Error(`导入缺口查看全部不得指向空日历：${gap.link}`);
    }
    if (!String(gap.link).includes('date_from') && !String(gap.link).includes('date=')) {
      throw new Error(`导入缺口查看全部缺少日期窗：${gap.link}`);
    }
  }

  await page.goto(
    `${config.adminUrl}/rider-salary/dashboard?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  const body = await page.locator('body').innerText();
  if (!body.includes('无方案日')) {
    throw new Error('工作台页面未见「无方案日」');
  }
  if (item.job_no && !body.includes(item.job_no) && !body.includes(item.name || '')) {
    console.warn('WARN: 页面表格可能折叠，API 已含无方案日行');
  }
  helpers.assertNoPaymentTaxCopy(body);
  await helpers.shot(page, 'cdp-ops-dashboard-no-plan-live');
}
