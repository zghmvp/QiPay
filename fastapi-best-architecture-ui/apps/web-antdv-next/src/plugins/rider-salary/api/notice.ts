import type { PageResult } from '../types/common';
import type { NoticeForm, NoticeQuery, NoticeResult } from '../types/notice';

import { requestClient } from '#/api/request';

const BASE = '/api/v1/rider-salary/notices';

export async function getNoticeListApi(params: NoticeQuery) {
  return requestClient.get<PageResult<NoticeResult>>(BASE, { params });
}

export async function getNoticeApi(pk: number) {
  return requestClient.get<NoticeResult>(`${BASE}/${pk}`);
}

export async function createNoticeApi(data: NoticeForm) {
  return requestClient.post(BASE, data);
}

export async function updateNoticeApi(pk: number, data: Partial<NoticeForm>) {
  return requestClient.put(`${BASE}/${pk}`, data);
}

export async function publishNoticeApi(pk: number) {
  return requestClient.post(`${BASE}/${pk}/publish`);
}

export async function offlineNoticeApi(pk: number) {
  return requestClient.post(`${BASE}/${pk}/offline`);
}

export async function deleteNoticeApi(pk: number) {
  return requestClient.delete(`${BASE}/${pk}`);
}
