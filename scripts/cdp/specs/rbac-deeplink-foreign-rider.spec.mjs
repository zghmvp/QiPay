import { RBAC, api, injectAndOpen, isDenied, loginAs } from '../rbac-helpers.mjs';

export const name = 'rbac-deeplink-foreign-rider';

export async function run({ page, helpers }) {
  const ow = await loginAs(RBAC.ownerUser, RBAC.ownerPass);
  const riders = await api(ow.access_token, 'GET', '/api/v1/rider-salary/riders?page=1&size=5&keyword=RBAC-RB');
  const foreignId = riders.json?.data?.items?.[0]?.id;
  const target = foreignId || 999999;
  const detail = await api(ow.access_token, 'GET', `/api/v1/rider-salary/riders/${target}`);
  if (!isDenied(detail)) throw new Error(`深链骑手 API 未拒绝 ${detail.status}`);
  await injectAndOpen(page, ow.access_token, ow.session_uuid || ow.user?.uuid || null, `/rider-salary/rider/${target}`);
  const body = await page.locator('body').innerText();
  if (body.includes('权限骑手B') && !/无权|不存在|403|404/.test(body)) {
    throw new Error('深链外站骑手页露出业务体');
  }
  await helpers.shot(page, 'rbac-deeplink-foreign-rider');
}
