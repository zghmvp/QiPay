import type { PageResult } from '../types/common';
import type { SubjectForm, SubjectQuery, SubjectResult } from '../types/subject';

import { requestClient } from '#/api/request';

const BASE = '/api/v1/rider-salary/subjects';

export async function getSubjectListApi(params: SubjectQuery) {
  return requestClient.get<PageResult<SubjectResult>>(BASE, { params });
}

export async function getAllSubjectsApi() {
  return requestClient.get<SubjectResult[]>(`${BASE}/all`);
}

export async function getSubjectApi(pk: number) {
  return requestClient.get<SubjectResult>(`${BASE}/${pk}`);
}

export async function createSubjectApi(data: SubjectForm) {
  return requestClient.post(BASE, data);
}

export async function updateSubjectApi(pk: number, data: Partial<SubjectForm>) {
  return requestClient.put(`${BASE}/${pk}`, data);
}

export async function deleteSubjectApi(pk: number) {
  return requestClient.delete(`${BASE}/${pk}`);
}
