/**
 * 管理端 A1–A7 与骑手 H5 B1–B6 验收。
 *
 * 用法（仓库根目录）：
 *   node scripts/t2_acceptance.mjs
 *
 * 账号、服务地址、截图目录见 scripts/README.md。
 * 默认演示账号：管理端 admin / 123456，骑手 D5A001 / Rider@123456。
 * 至少管理端和骑手 H5 各走一次真实登录页；验证码从 Redis 读取。
 * 写操作只新建再删除一条草稿公告（标题前缀 P111验收），不改 D5A/D5B 周期和薪资单。
 * 任一断言失败时进程以非 0 退出。
 */
import {
  ADMIN,
  API,
  H5,
  ADMIN_USER,
  RIDER_USER,
  assertNoticeRoundtrip,
  assertReachable,
  attachHttpGuard,
  cleanupProbeNotices,
  createRunner,
  finish,
  launchBrowser,
  loginAdmin,
  loginH5,
  readAdminToken,
  resolveDemo,
  shotDir,
  visitPage,
} from './acceptance-common.mjs';

const OUT = shotDir('t2');
const MONTH = process.env.QIPAY_MONTH || '2026-09';

function adminPages(demo) {
  const site = demo.site.id;
  const rider = demo.rider.id;
  const pages = [
    {
      name: '工作台',
      shot: 'A1-工作台',
      url: `${ADMIN}/rider-salary/dashboard?site_id=${site}&month=${MONTH}`,
      urlIncludes: '/rider-salary/dashboard',
      texts: ['在职骑手', '刷新'],
      banned: ['工作台加载失败'],
    },
    {
      name: '薪资日历',
      shot: 'A2-日历色带',
      url: `${ADMIN}/rider-salary/calendar?site_id=${site}&rider_id=${rider}&month=${MONTH}`,
      urlIncludes: '/rider-salary/calendar',
      texts: ['导出当月明细', '本月累计单量'],
      banned: ['日历加载失败'],
    },
    {
      name: '订单明细',
      shot: 'A4-订单页',
      url: `${ADMIN}/rider-salary/order`,
      urlIncludes: '/rider-salary/order',
      texts: ['订单号', '下单'],
    },
    {
      name: '结算周期',
      shot: 'A5-结算周期',
      url: `${ADMIN}/rider-salary/period`,
      urlIncludes: '/rider-salary/period',
      texts: ['周期区间', '应发合计'],
    },
    {
      name: '预支审核',
      shot: 'A6-预支审核',
      url: `${ADMIN}/rider-salary/advance`,
      urlIncludes: '/rider-salary/advance',
      texts: ['申请时间', '已抵扣'],
    },
    {
      name: '薪资方案',
      shot: 'A7-方案管理',
      url: `${ADMIN}/rider-salary/plan`,
      urlIncludes: '/rider-salary/plan',
      texts: ['短名', '版本号'],
    },
  ];
  if (demo.period?.id) {
    pages.splice(2, 0, {
      name: '周期详情',
      shot: 'A3-周期详情',
      url: `${ADMIN}/rider-salary/period?id=${demo.period.id}`,
      urlIncludes: '/rider-salary/period',
      texts: ['周期详情', '工号'],
    });
  }
  return pages;
}

function h5Pages() {
  return [
    {
      name: 'H5首页',
      shot: 'B1-首页',
      url: `${H5}/home`,
      urlIncludes: '/home',
      texts: ['本期薪资', '月历'],
    },
    {
      name: 'H5日详情',
      shot: 'B2-日详情',
      url: `${H5}/day/${MONTH}-10`,
      urlIncludes: `/day/${MONTH}-10`,
      texts: [`${MONTH}-10 明细`, '订单列表'],
    },
    {
      name: 'H5当前方案',
      shot: 'B3-当前方案',
      url: `${H5}/plan`,
      urlIncludes: '/plan',
      texts: ['当前方案'],
    },
    {
      name: 'H5奖惩明细',
      shot: 'B4-奖惩明细',
      url: `${H5}/adjustments`,
      urlIncludes: '/adjustments',
      texts: ['奖惩明细'],
    },
    {
      name: 'H5预支',
      shot: 'B5-预支',
      url: `${H5}/advance`,
      urlIncludes: '/advance',
      texts: ['申请预支'],
    },
    {
      name: 'H5公告',
      shot: 'B6-公告',
      url: `${H5}/notices`,
      urlIncludes: '/notices',
      texts: ['公告'],
    },
  ];
}

async function main() {
  console.log(`管理端账号 ${ADMIN_USER}，骑手 ${RIDER_USER}，截图 ${OUT}`);
  await assertReachable(`${API}/docs`, '后端');
  await assertReachable(`${ADMIN}/auth/login`, '管理端');
  await assertReachable(`${H5}/login`, '骑手 H5');

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
    console.log(`演示站点 ${demo.site.code || demo.site.id}，骑手 ${demo.rider.job_no}，周期 ${demo.period?.id || '无'}`);
    for (const spec of adminPages(demo)) {
      await visitPage(page, guard, runner, OUT, spec);
    }
    await assertNoticeRoundtrip(page, guard, runner, OUT, token);
    token = '';

    const h5 = await context.newPage();
    await h5.setViewportSize({ width: 390, height: 844 });
    const h5Guard = attachHttpGuard(h5);
    await loginH5(h5);
    for (const spec of h5Pages()) {
      await visitPage(h5, h5Guard, runner, OUT, spec);
    }
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
