import { RBAC, api, injectAndOpen, loginAs } from '../rbac-helpers.mjs';

export const name = 'rbac-audit-owner-foreign-rows';

export async function run({ page, helpers }) {
  const ow = await loginAs(RBAC.ownerUser, RBAC.ownerPass);
  const logs = await api(ow.access_token, 'GET', '/api/v1/rider-salary/audit-logs?page=1&size=100');
  if (logs.status >= 400) throw new Error(`审计列表失败 ${logs.status} ${logs.msg}`);
  const blob = JSON.stringify(logs.json?.data || {});
  const leaked = ['权限站B', 'RBACB', 'RBAC-OB-001', 'RBAC-ADJ-B'].filter((m) => blob.includes(m));
  await injectAndOpen(page, ow.access_token, ow.user?.uuid ?? null, '/rider-salary/audit');
  await helpers.shot(page, 'rbac-audit-owner-foreign-rows');
  if (leaked.length) {
    throw new Error(`日志页/API 出现站 B 对象：${leaked.join('、')}（与 api-rbac-audit-site-scope 同红）`);
  }
}
