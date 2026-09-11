import type { PageResult } from '../types/common';
import type {
  ActivePlanVersion,
  CreatePlanVersionParam,
  PlanDetail,
  PlanForm,
  PlanItemParam,
  PlanQuery,
  PlanVersionDetail,
  PlanVersionQuery,
  RollbackParam,
  RollbackPreviewResult,
  TrialParam,
  TrialResult,
  UpdatePlanVersionParam,
} from '../types/plan';

import { requestClient } from '#/api/request';

const PLAN_BASE = '/api/v1/rider-salary/plans';
const VERSION_BASE = '/api/v1/rider-salary/plan-versions';

function hasId(value: unknown): value is { id: number } {
  return (
    !!value &&
    typeof value === 'object' &&
    typeof (value as { id?: unknown }).id === 'number' &&
    Number.isFinite((value as { id: number }).id)
  );
}

export async function getActivePlanVersionsApi() {
  try {
    return await requestClient.get<ActivePlanVersion[]>(
      `${VERSION_BASE}/active`,
    );
  } catch {
    return [] as ActivePlanVersion[];
  }
}

export async function getPlanListApi(params: PlanQuery) {
  return requestClient.get<PageResult<PlanDetail>>(PLAN_BASE, { params });
}

export async function getPlanApi(pk: number) {
  return requestClient.get<PlanDetail>(`${PLAN_BASE}/${pk}`);
}

export async function createPlanApi(data: PlanForm) {
  const res = await requestClient.post<PlanDetail>(PLAN_BASE, data);
  if (hasId(res)) return res;
  const page = await getPlanListApi({ name: data.name, page: 1, size: 50 });
  const hit =
    (page?.items ?? []).find((item) => item.code === data.code) ??
    [...(page?.items ?? [])].sort((a, b) => b.id - a.id)[0];
  if (!hit) throw new Error('创建方案成功但未返回 ID，请刷新列表');
  return hit;
}

export async function updatePlanApi(pk: number, data: Partial<PlanForm>) {
  return requestClient.put(`${PLAN_BASE}/${pk}`, data);
}

export async function deletePlanApi(pk: number) {
  return requestClient.delete(`${PLAN_BASE}/${pk}`);
}

export async function getPlanVersionListApi(params: PlanVersionQuery) {
  return requestClient.get<PageResult<PlanVersionDetail>>(VERSION_BASE, {
    params,
  });
}

export async function getPlanVersionApi(pk: number) {
  return requestClient.get<PlanVersionDetail>(`${VERSION_BASE}/${pk}`);
}

export async function createPlanVersionApi(data: CreatePlanVersionParam) {
  const res = await requestClient.post<PlanVersionDetail>(VERSION_BASE, data);
  if (hasId(res)) return res;
  const page = await getPlanVersionListApi({
    page: 1,
    plan_id: data.plan_id,
    size: 50,
    status: 'draft',
  });
  const hit = [...(page?.items ?? [])].sort(
    (a, b) => b.version_no - a.version_no,
  )[0];
  if (!hit) throw new Error('创建版本成功但未返回 ID，请刷新列表');
  return hit;
}

export async function updatePlanVersionApi(
  pk: number,
  data: UpdatePlanVersionParam,
) {
  return requestClient.put(`${VERSION_BASE}/${pk}`, data);
}

export async function deletePlanVersionApi(pk: number) {
  return requestClient.delete(`${VERSION_BASE}/${pk}`);
}

export async function putPlanVersionItemsApi(
  pk: number,
  items: PlanItemParam[],
) {
  return requestClient.put<PlanVersionDetail>(
    `${VERSION_BASE}/${pk}/items`,
    items,
  );
}

export async function trialPlanVersionApi(pk: number, data: TrialParam) {
  return requestClient.post<TrialResult>(`${VERSION_BASE}/${pk}/trial`, data);
}

export async function activatePlanVersionApi(pk: number) {
  return requestClient.post(`${VERSION_BASE}/${pk}/activate`);
}

export async function disablePlanVersionApi(pk: number, reason: string) {
  return requestClient.post(`${VERSION_BASE}/${pk}/disable`, { reason });
}

export async function copyPlanVersionApi(pk: number, planId?: number) {
  const res = await requestClient.post<PlanVersionDetail>(
    `${VERSION_BASE}/${pk}/copy`,
  );
  if (hasId(res)) return res;
  if (!planId) throw new Error('复制成功但未返回 ID，请刷新列表');
  const page = await getPlanVersionListApi({
    page: 1,
    plan_id: planId,
    size: 50,
    status: 'draft',
  });
  const hit = [...(page?.items ?? [])].sort(
    (a, b) => b.version_no - a.version_no,
  )[0];
  if (!hit) throw new Error('复制成功但未返回 ID，请刷新列表');
  return hit;
}

export async function getRollbackPreviewApi(pk: number) {
  return requestClient.get<RollbackPreviewResult>(
    `${VERSION_BASE}/${pk}/rollback-preview`,
  );
}

export async function rollbackPlanVersionApi(pk: number, data: RollbackParam) {
  return requestClient.post(`${VERSION_BASE}/${pk}/rollback`, data);
}
