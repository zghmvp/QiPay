import { RBAC, api, injectAndOpen, isDenied, loginAs } from '../rbac-helpers.mjs';

export const name = 'rbac-plan-editor-url-owner';

export async function run({ page, helpers }) {
  const ow = await loginAs(RBAC.ownerUser, RBAC.ownerPass);
  const vers = await api(ow.access_token, 'GET', '/api/v1/rider-salary/plan-versions?page=1&size=5');
  const ver = vers.json?.data?.items?.[0];
  if (!ver) throw new Error('无方案版本，无法测编辑器深链');
  const detail = await api(ow.access_token, 'GET', `/api/v1/rider-salary/plan-versions/${ver.id}`);
  if (detail.status >= 400) throw new Error(`SO GET 版本失败 ${detail.status}（缺口 #4 应变为 200）`);
  const text = JSON.stringify(detail.json?.data || {});
  if (!text.includes('formula') && !text.includes('items')) {
    throw new Error('版本详情未见公式/方案项 JSON');
  }
  const put = await api(ow.access_token, 'PUT', `/api/v1/rider-salary/plan-versions/${ver.id}/items`, []);
  if (!isDenied(put)) throw new Error('SO PUT items 未 403');
  await injectAndOpen(page, ow.access_token, ow.session_uuid || ow.user?.uuid || null, `/rider-salary/plan/editor/${ver.id}`);
  await page.waitForTimeout(1000);
  const url = page.url();
  const body = await page.locator('body').innerText();
  const blocked =
    /404|无权限|不存在|找不到/.test(body) ||
    !url.includes('/plan/editor/') ||
    (await page.locator('.ant-result-404, .ant-result').count()) > 0;
  const writable =
    url.includes('/plan/editor/') &&
    ((await page.locator('button:has-text("保存")').count()) > 0 ||
      (await page.locator('button:has-text("启用")').count()) > 0);
  if (!blocked && writable) {
    throw new Error('负责人打开了方案编辑器写入口');
  }
  await helpers.shot(page, 'rbac-plan-editor-url-owner');
}
