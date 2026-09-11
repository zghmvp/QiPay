import type { DayFlagResult, UpsertDayFlagParam } from '../types/day-flag';

import { requestClient } from '#/api/request';

const BASE = '/api/v1/rider-salary/day-flags';

export async function getDayFlagsApi(params: { month: string; site_id: number }) {
  return requestClient.get<DayFlagResult[]>(BASE, { params });
}

export async function upsertDayFlagsApi(data: UpsertDayFlagParam) {
  return requestClient.put(BASE, data);
}
