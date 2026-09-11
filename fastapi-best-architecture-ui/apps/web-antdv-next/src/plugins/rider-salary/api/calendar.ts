import type {
  CalendarDayDetail,
  CalendarMonth,
} from '../types/calendar';

import { requestClient } from '#/api/request';

const BASE = '/api/v1/rider-salary/calendar';

export async function getCalendarMonthApi(riderId: number, month: string) {
  return requestClient.get<CalendarMonth>(`${BASE}/${riderId}`, {
    params: { month },
  });
}

export async function getCalendarDayApi(riderId: number, date: string) {
  return requestClient.get<CalendarDayDetail>(
    `${BASE}/${riderId}/days/${date}`,
  );
}
