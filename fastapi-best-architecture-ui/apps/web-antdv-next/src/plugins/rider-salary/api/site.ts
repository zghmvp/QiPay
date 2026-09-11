import type { PageResult } from '../types/common';
import type {
  SiteForm,
  SiteManagerItem,
  SiteManagerResult,
  SiteQuery,
  SiteResult,
} from '../types/site';

import { requestClient } from '#/api/request';

const BASE = '/api/v1/rider-salary/sites';

export async function getSiteListApi(params: SiteQuery) {
  return requestClient.get<PageResult<SiteResult>>(BASE, { params });
}

export async function getAllSitesApi() {
  return requestClient.get<SiteResult[]>(`${BASE}/all`);
}

export async function getSiteApi(pk: number) {
  return requestClient.get<SiteResult>(`${BASE}/${pk}`);
}

export async function createSiteApi(data: SiteForm) {
  return requestClient.post(BASE, data);
}

export async function updateSiteApi(pk: number, data: Partial<SiteForm>) {
  return requestClient.put(`${BASE}/${pk}`, data);
}

export async function deleteSiteApi(pk: number) {
  return requestClient.delete(`${BASE}/${pk}`);
}

export async function getSiteManagersApi(pk: number) {
  return requestClient.get<SiteManagerResult[]>(`${BASE}/${pk}/managers`);
}

export async function updateSiteManagersApi(
  pk: number,
  managers: SiteManagerItem[],
) {
  return requestClient.put(`${BASE}/${pk}/managers`, managers);
}
