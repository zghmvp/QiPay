/**
 * 小象波 CDP 夹具灌种（幂等）：FIX_C17_R1 无方案有单日 + site_owner_d2 + ≥2 stale
 * + FIX_C17_LOCK 骑手级开放周期（零 stale，供 ops-lock-preflight-hard-fail）。
 *
 * 仅调用管理端/插件 API（admin token）；不改 FBA 框架、不 wipe 灯塔订单。
 * 正式验收禁止把 Must #5 改成超管登录。
 * 本脚本不依赖 playwright（可在无 CDP Chrome 的机器上先灌种）。
 *
 * 用法：
 *   API_URL=http://127.0.0.1:8000 CDP_USER=admin CDP_PASS=admin \
 *     node scripts/cdp/seed-xiaoxiang-fixtures.mjs
 *
 * 可选：CDP_SITE_CODE=SZ0050  CDP_MONTH=2026-09
 */
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '../..');
const FIXTURE = path.join(
  ROOT,
  'fastapi-best-architecture/backend/plugin/rider_salary/tests/fixtures/trial-binding-segments/seed.json',
);

const API_URL = process.env.API_URL || 'http://127.0.0.1:8000';
const ADMIN_USER = process.env.CDP_USER || 'admin';
const ADMIN_PASS = process.env.CDP_PASS || '123456';
const SITE_CODE = process.env.CDP_SITE_CODE || 'SZ0050';
const MONTH = process.env.CDP_MONTH || '2026-09';
const JOB_NO = 'FIX_C17_R1';
const LOCK_JOB_NO = 'FIX_C17_LOCK';
const OWNER_USER = process.env.CDP_SITE_OWNER || 'site_owner_d2';
const OWNER_PASS = process.env.CDP_SITE_OWNER_PASS || 'Rider@123456';
const OWNER_ROLE_ID = Number(process.env.CDP_SITE_OWNER_ROLE_ID || '92002');
const STALE_REMARK = 'FIX_STALE_SEED';
const ORDER_PREFIX = 'FIX_C17_';
const LOCK_ORDER_PREFIX = 'FIX_C17_LOCK_';
const LOCK_ORDER_DAY = '2026-09-20';

async function swaggerLogin(username, password) {
  const res = await fetch(
    `${API_URL}/api/v1/auth/login/swagger?username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`,
    { method: 'POST' },
  );
  if (!res.ok) {
    throw new Error(`login failed ${username}: ${res.status}`);
  }
  return res.json();
}

function authHeaders(token) {
  return {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  };
}

async function api(token, method, urlPath, body) {
  const res = await fetch(`${API_URL}${urlPath}`, {
    method,
    headers: authHeaders(token),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let json = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = { raw: text };
  }
  if (!res.ok) {
    const msg = json?.msg || json?.detail || text || res.statusText;
    throw new Error(`${method} ${urlPath} → ${res.status}: ${msg}`);
  }
  return json;
}

async function findSite(token) {
  const all = await api(token, 'GET', '/api/v1/rider-salary/sites/all');
  const sites = all?.data || [];
  const hit = sites.find((s) => s.code === SITE_CODE);
  if (!hit) {
    throw new Error(`未找到站点 ${SITE_CODE}；请先灌灯塔福民切片`);
  }
  return hit;
}

async function findRiderByJobNo(token, siteId, jobNo) {
  const qs = new URLSearchParams({
    page: '1',
    size: '50',
    site_id: String(siteId),
    keyword: jobNo,
  });
  const page = await api(token, 'GET', `/api/v1/rider-salary/riders?${qs}`);
  const items = page?.data?.items || [];
  return items.find((r) => r.job_no === jobNo) || null;
}

async function ensureFixRider(token, siteId) {
  let rider = await findRiderByJobNo(token, siteId, JOB_NO);
  if (!rider) {
    await api(token, 'POST', '/api/v1/rider-salary/riders', {
      job_no: JOB_NO,
      name: '换绑夹具骑手',
      phone: null,
      site_id: siteId,
      employ_type: 'part_time',
      hire_date: '2026-09-01',
      leave_date: null,
      status: 'on_job',
      advance_limit: null,
      settle_cycle_override: null,
      cycle_config_override: null,
      remark: 'FIX_C17 日历深链/分段试算夹具',
    });
    rider = await findRiderByJobNo(token, siteId, JOB_NO);
    if (!rider) throw new Error('创建 FIX_C17_R1 后仍查不到骑手');
    console.log('created rider', JOB_NO, 'id=', rider.id);
  } else {
    console.log('reuse rider', JOB_NO, 'id=', rider.id);
  }
  return rider;
}

async function pickPlanVersions(token) {
  const res = await api(token, 'GET', '/api/v1/rider-salary/plan-versions/active');
  const list = res?.data || [];
  if (!list.length) {
    throw new Error('无启用方案版本；请先创建灯塔演示方案');
  }
  const a = list[0];
  const b = list.find((v) => v.id !== a.id) || a;
  if (b.id === a.id) {
    console.warn(
      'WARN: 仅一个启用方案版本，段 A/B 共用同一 version（日历深链仍可用；字段对照金标需第二方案）',
    );
  }
  return { planA: a.id, planB: b.id };
}

async function ensureBindings(token, riderId, planA, planB) {
  const list = await api(token, 'GET', `/api/v1/rider-salary/riders/${riderId}/bindings`);
  const existing = list?.data || [];
  for (const row of existing) {
    await api(token, 'DELETE', `/api/v1/rider-salary/riders/${riderId}/bindings/${row.id}`);
  }
  const specs = [
    {
      plan_version_id: planA,
      binding_type: 'default',
      start_date: '2026-09-01',
      end_date: '2026-09-14',
      remark: 'FIX_C17 段A',
    },
    {
      plan_version_id: planB,
      binding_type: 'default',
      start_date: '2026-09-18',
      end_date: '2026-09-30',
      remark: 'FIX_C17 段B',
    },
  ];
  for (const body of specs) {
    await api(token, 'POST', `/api/v1/rider-salary/riders/${riderId}/bindings`, body);
  }
  console.log('bindings set: 09-01~14 + 09-18~30 (gap 15~17)');
}

/**
 * 绑定挖洞后若曾算薪留下 rs_payroll_daily，缺口日会被缓存盖成 has_data。
 * 写路径会失效绑定区间内 daily，但缺口日本身不在任一段 → 必须显式清 15~17。
 * 只改绑定不够；见 council-resolution-calendar-cache-cdp。
 */
function clearGapPayrollDailies(riderId) {
  const days = ['2026-09-15', '2026-09-16', '2026-09-17'];
  const host = process.env.PGHOST || '127.0.0.1';
  const port = process.env.PGPORT || '5432';
  const user = process.env.PGUSER || 'root';
  const db = process.env.PGDATABASE || 'fba';
  const password = process.env.PGPASSWORD || 'postgres';
  const dayList = days.map((d) => `'${d}'::date`).join(', ');
  const sql = `
UPDATE rs_payroll_daily
    SET deleted = id, deleted_time = NOW()
  WHERE rider_id = ${Number(riderId)}
    AND biz_date IN (${dayList})
    AND deleted = 0;
`;
  try {
    const out = execFileSync(
      'psql',
      ['-h', host, '-p', String(port), '-U', user, '-d', db, '-v', 'ON_ERROR_STOP=1', '-c', sql],
      {
        env: { ...process.env, PGPASSWORD: password },
        encoding: 'utf8',
      },
    );
    console.log('cleared gap payroll_daily for rider', riderId, 'days', days.join(','), out.trim());
  } catch (err) {
    console.warn(
      'WARN: 未能清缺口日 rs_payroll_daily（日历读路径仍应以 live 绑定判 no_plan；工作台 attention 可能需手工清）:',
      err.message || err,
    );
  }
}

async function ensureNoPlanOrders(token, siteId, riderId) {
  const days = ['2026-09-15', '2026-09-16', '2026-09-17'];
  const perDay = 5;
  let created = 0;
  for (const day of days) {
    for (let i = 1; i <= perDay; i += 1) {
      const orderNo = `${ORDER_PREFIX}${day.replaceAll('-', '')}_${String(i).padStart(2, '0')}`;
      const orderTime = `${day}T10:${String(i).padStart(2, '0')}:00+08:00`;
      const deliverTime = `${day}T11:${String(i).padStart(2, '0')}:00+08:00`;
      try {
        await api(token, 'POST', '/api/v1/rider-salary/orders', {
          order_no: orderNo,
          site_id: siteId,
          rider_id: riderId,
          distance_km: '3.00',
          weight_jin: '4.00',
          order_time: orderTime,
          deliver_time: deliverTime,
          status: 'completed',
          amount: '20.00',
          remark: 'FIX_C17 无方案日夹具单',
        });
        created += 1;
      } catch (err) {
        const msg = String(err.message || err);
        if (/已存在|重复|conflict|409/i.test(msg)) {
          continue;
        }
        throw err;
      }
    }
  }
  console.log(`no-plan orders: created=${created} (idempotent skip on dup)`);
}

async function findUserByUsername(token, username) {
  const qs = new URLSearchParams({ page: '1', size: '20', username });
  const page = await api(token, 'GET', `/api/v1/sys/users?${qs}`);
  const items = page?.data?.items || [];
  return items.find((u) => u.username === username) || null;
}

async function ensureSiteOwner(token, siteId) {
  let user = await findUserByUsername(token, OWNER_USER);
  if (!user) {
    const created = await api(token, 'POST', '/api/v1/sys/users', {
      username: OWNER_USER,
      password: OWNER_PASS,
      nickname: '福民站负责人',
      email: null,
      phone: null,
      dept_id: 1,
      roles: [OWNER_ROLE_ID],
    });
    user = created?.data || (await findUserByUsername(token, OWNER_USER));
    if (!user?.id) throw new Error('创建 site_owner_d2 失败');
    console.log('created user', OWNER_USER, 'id=', user.id);
  } else {
    console.log('reuse user', OWNER_USER, 'id=', user.id);
    const roleIds = Array.from(
      new Set([...(user.roles?.map((r) => r.id || r) || []), OWNER_ROLE_ID].map(Number)),
    );
    await api(token, 'PUT', `/api/v1/sys/users/${user.id}`, {
      dept_id: user.dept_id || 1,
      username: user.username,
      nickname: user.nickname || '福民站负责人',
      avatar: user.avatar || null,
      email: user.email || null,
      phone: user.phone || null,
      roles: roleIds,
    });
  }

  if (!user.is_staff) {
    await api(token, 'PUT', `/api/v1/sys/users/${user.id}/permissions?type=staff`);
    console.log('enabled is_staff for', OWNER_USER);
  }
  if (!user.is_multi_login) {
    try {
      await api(token, 'PUT', `/api/v1/sys/users/${user.id}/permissions?type=multi_login`);
    } catch {
      /* optional */
    }
  }

  try {
    await api(token, 'PUT', `/api/v1/sys/users/${user.id}/password`, { password: OWNER_PASS });
  } catch (err) {
    console.warn('WARN: reset password skipped:', err.message);
  }

  const mgrRes = await api(token, 'GET', `/api/v1/rider-salary/sites/${siteId}/managers`);
  const managers = (mgrRes?.data || []).map((m) => ({ user_id: m.user_id, role: m.role }));
  const already = managers.find((m) => m.user_id === user.id);
  if (!already) {
    const hasOwner = managers.some((m) => m.role === 'owner');
    managers.push({ user_id: user.id, role: hasOwner ? 'deputy' : 'owner' });
    await api(token, 'PUT', `/api/v1/rider-salary/sites/${siteId}/managers`, managers);
    console.log(
      `linked ${OWNER_USER} as ${hasOwner ? 'deputy' : 'owner'} on site ${siteId}`,
    );
  } else {
    console.log(`${OWNER_USER} already site manager role=${already.role}`);
  }

  const login = await swaggerLogin(OWNER_USER, OWNER_PASS);
  if (!login?.access_token) {
    throw new Error(`${OWNER_USER} swagger 登录失败`);
  }
  console.log('site owner swagger login OK');
  return user;
}

async function listRidersWithPayroll(token, siteId) {
  const qs = new URLSearchParams({
    page: '1',
    size: '50',
    site_id: String(siteId),
  });
  const page = await api(token, 'GET', `/api/v1/rider-salary/riders?${qs}`);
  return (page?.data?.items || []).filter(
    (r) => r.job_no !== JOB_NO && r.job_no !== LOCK_JOB_NO,
  );
}

async function ensureStalePayrolls(token, siteId) {
  const riders = await listRidersWithPayroll(token, siteId);
  if (riders.length < 2) {
    throw new Error('福民站可用骑手不足 2 人，无法造 stale（请先灌灯塔切片）');
  }
  const targets = riders.slice(0, 2);
  const bizDate = `${MONTH}-15`;
  for (const rider of targets) {
    try {
      await api(token, 'POST', '/api/v1/rider-salary/adjustments', {
        rider_id: rider.id,
        biz_date: bizDate,
        subject_id: 94019,
        amount: '1.00',
        remark: `${STALE_REMARK} ${rider.job_no}`,
      });
      console.log('marked stale via adjustment:', rider.job_no, rider.id);
    } catch (err) {
      const msg = String(err.message || err);
      if (/锁账|已锁/.test(msg)) throw err;
      console.warn('WARN: adjustment for', rider.job_no, msg);
    }
  }

  try {
    const preview = await api(token, 'POST', '/api/v1/rider-salary/dashboard/stale-batch/preview', {
      site_id: siteId,
      month: MONTH,
    });
    const staleCount = preview?.data?.stale_rider_count ?? preview?.data?.stale_count;
    console.log('stale-batch preview:', JSON.stringify(preview?.data ?? preview));
    if (staleCount != null && Number(staleCount) < 2) {
      console.warn(
        `WARN: stale_rider_count=${staleCount} < 2；请确认周期已 calculate 且奖惩命中开放月`,
      );
    }
  } catch (err) {
    console.warn('WARN: stale preview skipped:', err.message);
  }
}

async function clearRiderBindings(token, riderId) {
  const list = await api(token, 'GET', `/api/v1/rider-salary/riders/${riderId}/bindings`);
  for (const row of list?.data || []) {
    await api(token, 'DELETE', `/api/v1/rider-salary/riders/${riderId}/bindings/${row.id}`);
  }
}

/**
 * 独立骑手级周期：有完成单无方案、零 payroll / 零 stale。
 * 与站点月周期 1 分开，避免 stale-batch 污染；不在 CDP spec 里 generate。
 */
async function ensureLockHardFailRider(token, siteId) {
  let rider = await findRiderByJobNo(token, siteId, LOCK_JOB_NO);
  if (!rider) {
    await api(token, 'POST', '/api/v1/rider-salary/riders', {
      job_no: LOCK_JOB_NO,
      name: '锁账硬拦夹具骑手',
      phone: null,
      site_id: siteId,
      employ_type: 'part_time',
      hire_date: '2026-09-01',
      leave_date: null,
      status: 'on_job',
      advance_limit: null,
      settle_cycle_override: 'month',
      cycle_config_override: null,
      remark: 'FIX_C17_LOCK 无 stale 硬失败周期夹具',
    });
    rider = await findRiderByJobNo(token, siteId, LOCK_JOB_NO);
    if (!rider) throw new Error('创建 FIX_C17_LOCK 后仍查不到骑手');
    console.log('created rider', LOCK_JOB_NO, 'id=', rider.id);
  } else {
    console.log('reuse rider', LOCK_JOB_NO, 'id=', rider.id);
    if (rider.settle_cycle_override !== 'month') {
      await api(token, 'PUT', `/api/v1/rider-salary/riders/${rider.id}`, {
        settle_cycle_override: 'month',
      });
      console.log('set settle_cycle_override=month for', LOCK_JOB_NO);
    }
  }
  await clearRiderBindings(token, rider.id);
  return rider;
}

async function ensureLockHardFailOrders(token, siteId, riderId) {
  let created = 0;
  for (let i = 1; i <= 3; i += 1) {
    const orderNo = `${LOCK_ORDER_PREFIX}${LOCK_ORDER_DAY.replaceAll('-', '')}_${String(i).padStart(2, '0')}`;
    try {
      await api(token, 'POST', '/api/v1/rider-salary/orders', {
        order_no: orderNo,
        site_id: siteId,
        rider_id: riderId,
        distance_km: '3.00',
        weight_jin: '4.00',
        order_time: `${LOCK_ORDER_DAY}T10:${String(i).padStart(2, '0')}:00+08:00`,
        deliver_time: `${LOCK_ORDER_DAY}T11:${String(i).padStart(2, '0')}:00+08:00`,
        status: 'completed',
        amount: '20.00',
        remark: 'FIX_C17_LOCK 无方案有单夹具',
      });
      created += 1;
    } catch (err) {
      const msg = String(err.message || err);
      if (/已存在|重复|conflict|409/i.test(msg)) {
        continue;
      }
      throw err;
    }
  }
  console.log(`lock-hard-fail orders: created=${created} day=${LOCK_ORDER_DAY}`);
}

async function ensureLockHardFailPeriod(token, siteId, riderId) {
  const generated = await api(token, 'POST', '/api/v1/rider-salary/periods/generate', {
    site_id: siteId,
    month: MONTH,
  });
  console.log(
    'generate periods:',
    `created=${generated?.data?.created_count ?? '?'}`,
    `skipped=${generated?.data?.skipped_count ?? '?'}`,
  );

  const qs = new URLSearchParams({
    page: '1',
    size: '50',
    site_id: String(siteId),
    rider_id: String(riderId),
    month: MONTH,
  });
  const page = await api(token, 'GET', `/api/v1/rider-salary/periods?${qs}`);
  const items = page?.data?.items || [];
  const period = items.find(
    (row) =>
      Number(row.rider_id) === Number(riderId) &&
      (row.status === 'open' || row.status === 'reopened'),
  );
  if (!period?.id) {
    throw new Error('生成后仍找不到 FIX_C17_LOCK 骑手级开放周期');
  }
  if (Number(period.stale_count || 0) > 0) {
    throw new Error(
      `FIX_C17_LOCK 周期 ${period.id} 已有 stale draft，夹具被污染（禁止 UPDATE stale=false）`,
    );
  }
  console.log(
    'lock-hard-fail period',
    period.id,
    'rider_id=',
    period.rider_id,
    'stale_count=',
    period.stale_count ?? 0,
  );
  return period;
}

async function writeEnvHint(siteId, riderId, lockPeriodId, lockRiderId) {
  const outDir =
    process.env.CDP_MEDIA_DIR ||
    path.join(
      process.env.CURSOR_AGENT_STORE ||
        '/cursor/stores/bc-2955b371-f65c-4990-a229-d877e2ac6c7a',
      'media',
    );
  fs.mkdirSync(outDir, { recursive: true });
  const file = path.join(outDir, 'cdp-xiaoxiang-fixture-env.txt');
  const text = [
    `# generated by scripts/cdp/seed-xiaoxiang-fixtures.mjs`,
    `CDP_SITE_ID=${siteId}`,
    `CDP_RIDER_ID=${riderId}`,
    `CDP_MONTH=${MONTH}`,
    `CDP_SITE_OWNER=${OWNER_USER}`,
    `CDP_SITE_OWNER_PASS=${OWNER_PASS}`,
    `CDP_LOCK_HARD_FAIL_JOB_NO=${LOCK_JOB_NO}`,
    `CDP_LOCK_HARD_FAIL_PERIOD_ID=${lockPeriodId ?? ''}`,
    `CDP_LOCK_HARD_FAIL_RIDER_ID=${lockRiderId ?? ''}`,
    '',
  ].join('\n');
  fs.writeFileSync(file, text, 'utf8');
  console.log('wrote', file);
}

async function main() {
  const seed = JSON.parse(fs.readFileSync(FIXTURE, 'utf8'));
  console.log('fixture', seed.fixture, 'job_no', seed.rider.job_no);

  const admin = await swaggerLogin(ADMIN_USER, ADMIN_PASS);
  const token = admin.access_token;
  if (!token) throw new Error('admin swagger 登录失败');

  const site = await findSite(token);
  console.log('site', site.code, 'id=', site.id);

  const { planA, planB } = await pickPlanVersions(token);
  const rider = await ensureFixRider(token, site.id);
  await ensureBindings(token, rider.id, planA, planB);
  clearGapPayrollDailies(rider.id);
  await ensureNoPlanOrders(token, site.id, rider.id);
  await ensureSiteOwner(token, site.id);
  await ensureStalePayrolls(token, site.id);
  const lockRider = await ensureLockHardFailRider(token, site.id);
  await ensureLockHardFailOrders(token, site.id, lockRider.id);
  const lockPeriod = await ensureLockHardFailPeriod(token, site.id, lockRider.id);
  await writeEnvHint(site.id, rider.id, lockPeriod.id, lockRider.id);

  console.log('\n=== CDP env (copy) ===');
  console.log(`export CDP_SITE_ID=${site.id}`);
  console.log(`export CDP_RIDER_ID=${rider.id}`);
  console.log(`export CDP_MONTH=${MONTH}`);
  console.log(`export CDP_SITE_OWNER=${OWNER_USER}`);
  console.log(`export CDP_SITE_OWNER_PASS=${OWNER_PASS}`);
  console.log(`export CDP_LOCK_HARD_FAIL_JOB_NO=${LOCK_JOB_NO}`);
  console.log(`export CDP_LOCK_HARD_FAIL_PERIOD_ID=${lockPeriod.id}`);
  console.log(`export CDP_LOCK_HARD_FAIL_RIDER_ID=${lockRider.id}`);
  console.log('\nDone. Re-run:');
  console.log(
    `  CDP_URL=http://127.0.0.1:9222 CDP_PASS=${ADMIN_PASS} CDP_SITE_ID=${site.id} CDP_RIDER_ID=${rider.id} CDP_MONTH=${MONTH} node scripts/cdp/harness.mjs ops-calendar-no-plan-deeplink`,
  );
  console.log(
    `  CDP_URL=http://127.0.0.1:9222 CDP_SITE_ID=${site.id} CDP_MONTH=${MONTH} node scripts/cdp/harness.mjs ops-stale-batch-recalc`,
  );
  console.log(
    `  CDP_URL=http://127.0.0.1:9222 CDP_PASS=${ADMIN_PASS} CDP_SITE_ID=${site.id} CDP_MONTH=${MONTH} CDP_LOCK_HARD_FAIL_PERIOD_ID=${lockPeriod.id} node scripts/cdp/harness.mjs ops-lock-preflight-hard-fail`,
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
