/**
 * 管理端列表页高度验收：打开页面、断言关键文本、记录视口截图。
 *
 * 用法（仓库根目录）：
 *   node scripts/ux_check.mjs
 *
 * 账号与地址见 scripts/README.md。默认演示账号 admin / 123456。
 * 走真实登录页，验证码从 Redis 读取，不调用 /auth/login/swagger。
 * 写操作只新建再删除一条草稿公告（标题前缀 P111验收）。
 * 任一断言失败时进程以非 0 退出。
 */
import {
  ADMIN,
  API,
  ADMIN_USER,
  assertNoticeRoundtrip,
  assertReachable,
  attachHttpGuard,
  cleanupProbeNotices,
  createRunner,
  finish,
  launchBrowser,
  loginAdmin,
  readAdminToken,
  resolveDemo,
  shot,
  shotDir,
  visitPage,
} from './acceptance-common.mjs';

const OUT = shotDir('ux');
const MONTH = process.env.QIPAY_MONTH || '2026-09';

function pages(demo) {
  const site = demo.site.id;
  const rider = demo.rider.id;
  return [
    {
      name: '工作台',
      shot: '01-工作台',
      url: `${ADMIN}/rider-salary/dashboard?site_id=${site}&month=${MONTH}`,
      urlIncludes: '/rider-salary/dashboard',
      texts: ['在职骑手', '刷新'],
      banned: ['工作台加载失败'],
    },
    {
      name: '站点列表',
      shot: '02-站点列表',
      url: `${ADMIN}/rider-salary/site`,
      urlIncludes: '/rider-salary/site',
      texts: ['编码', '周期类型'],
    },
    {
      name: '订单列表',
      shot: '03-订单列表',
      url: `${ADMIN}/rider-salary/order`,
      urlIncludes: '/rider-salary/order',
      texts: ['订单号', '送达'],
    },
    {
      name: '结算周期',
      shot: '04-结算周期',
      url: `${ADMIN}/rider-salary/period`,
      urlIncludes: '/rider-salary/period',
      texts: ['周期区间', '实发合计'],
    },
    {
      name: '日历',
      shot: '05-日历',
      url: `${ADMIN}/rider-salary/calendar?site_id=${site}&rider_id=${rider}&month=${MONTH}`,
      urlIncludes: '/rider-salary/calendar',
      texts: ['导出当月明细', '本月累计单量'],
      banned: ['日历加载失败'],
    },
    {
      name: '方案管理',
      shot: '06-方案管理',
      url: `${ADMIN}/rider-salary/plan`,
      urlIncludes: '/rider-salary/plan',
      texts: ['短名', '版本号'],
    },
    {
      name: '骑手列表',
      shot: '07-骑手列表',
      url: `${ADMIN}/rider-salary/rider`,
      urlIncludes: '/rider-salary/rider',
      texts: ['工号', '用工类型'],
    },
  ];
}

async function main() {
  console.log(`管理端账号 ${ADMIN_USER}，截图 ${OUT}`);
  await assertReachable(`${API}/docs`, '后端');
  await assertReachable(`${ADMIN}/auth/login`, '管理端');

  const runner = createRunner();
  const browser = await launchBrowser();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const guard = attachHttpGuard(page);
  let token = '';
  try {
    await loginAdmin(page);
    token = await readAdminToken(page);
    await cleanupProbeNotices(token);
    const demo = await resolveDemo(token);
    for (const spec of pages(demo)) {
      await visitPage(page, guard, runner, OUT, spec);
    }
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.waitForTimeout(500);
    await shot(page, OUT, '08-骑手列表-resize-1280');
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.waitForTimeout(500);
    await shot(page, OUT, '09-骑手列表-resize-1440');
    const body = await page.locator('body').innerText();
    if (!body.includes('用工类型')) runner.fail('骑手列表缩放后缺少关键文本：用工类型');
    await assertNoticeRoundtrip(page, guard, runner, OUT, token);
    token = '';
  } finally {
    if (token) await cleanupProbeNotices(token).catch(() => {});
    await browser.close();
  }
  return finish(runner);
}

main()
  .then((code) => process.exit(code))
  .catch((error) => {
    if (!error?.failFast) console.error(error);
    process.exit(1);
  });
