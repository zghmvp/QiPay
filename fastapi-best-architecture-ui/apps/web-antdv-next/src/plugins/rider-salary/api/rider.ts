import type { PageResult } from '../types/common';
import type {
  EffectivePlanSegment,
  EmployHistoryForm,
  EmployHistoryResult,
  PlanBindingForm,
  PlanBindingResult,
  RiderAccountForm,
  RiderForm,
  RiderLeaveForm,
  RiderQuery,
  RiderResult,
} from '../types/rider';

import { requestClient } from '#/api/request';

const BASE = '/api/v1/rider-salary/riders';

export async function getRiderListApi(params: RiderQuery) {
  return requestClient.get<PageResult<RiderResult>>(BASE, { params });
}

export async function getRiderApi(pk: number) {
  return requestClient.get<RiderResult>(`${BASE}/${pk}`);
}

export async function createRiderApi(data: RiderForm) {
  return requestClient.post(BASE, data);
}

export async function updateRiderApi(pk: number, data: Partial<RiderForm>) {
  return requestClient.put(`${BASE}/${pk}`, data);
}

export async function deleteRiderApi(pk: number) {
  return requestClient.delete(`${BASE}/${pk}`);
}

export async function leaveRiderApi(pk: number, data: RiderLeaveForm) {
  return requestClient.put(`${BASE}/${pk}/leave`, data);
}

export async function getRiderBindingsApi(pk: number) {
  return requestClient.get<PlanBindingResult[]>(`${BASE}/${pk}/bindings`);
}

export async function createRiderBindingApi(pk: number, data: PlanBindingForm) {
  return requestClient.post(`${BASE}/${pk}/bindings`, data);
}

export async function updateRiderBindingApi(
  pk: number,
  bindingId: number,
  data: Partial<PlanBindingForm>,
) {
  return requestClient.put(`${BASE}/${pk}/bindings/${bindingId}`, data);
}

export async function deleteRiderBindingApi(pk: number, bindingId: number) {
  return requestClient.delete(`${BASE}/${pk}/bindings/${bindingId}`);
}

export async function getRiderEffectivePlansApi(
  pk: number,
  start: string,
  end: string,
) {
  return requestClient.get<EffectivePlanSegment[]>(`${BASE}/${pk}/effective-plans`, {
    params: { end, start },
  });
}

export async function getRiderEmployHistoryApi(pk: number) {
  return requestClient.get<EmployHistoryResult[]>(
    `${BASE}/${pk}/employ-history`,
  );
}

export async function createRiderEmployHistoryApi(
  pk: number,
  data: EmployHistoryForm,
) {
  return requestClient.post(`${BASE}/${pk}/employ-history`, data);
}

export async function updateRiderEmployHistoryApi(
  pk: number,
  historyId: number,
  data: Partial<EmployHistoryForm>,
) {
  return requestClient.put(`${BASE}/${pk}/employ-history/${historyId}`, data);
}

export async function deleteRiderEmployHistoryApi(
  pk: number,
  historyId: number,
) {
  return requestClient.delete(`${BASE}/${pk}/employ-history/${historyId}`);
}

export async function openRiderAccountApi(pk: number, data: RiderAccountForm) {
  return requestClient.post(`${BASE}/${pk}/open-account`, data);
}

export async function resetRiderPasswordApi(
  pk: number,
  data: RiderAccountForm,
) {
  return requestClient.post(`${BASE}/${pk}/reset-password`, data);
}

export async function disableRiderAccountApi(
  pk: number,
  data: RiderAccountForm,
) {
  return requestClient.post(`${BASE}/${pk}/disable-account`, data);
}

export async function enableRiderAccountApi(
  pk: number,
  data: RiderAccountForm,
) {
  return requestClient.post(`${BASE}/${pk}/enable-account`, data);
}
