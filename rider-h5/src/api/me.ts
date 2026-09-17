import { request } from '@/api/http'
import type {
  AdvanceDetail,
  AdvanceLimit,
  CalendarDayDetail,
  CalendarMonth,
  CreateAdvancePayload,
  MeAdjustmentItem,
  MePlan,
  MeProfile,
  PayrollEstimate,
} from '@/types'

const PREFIX = '/api/v1/rider-salary/me'

export function getProfile() {
  return request<MeProfile>({ url: `${PREFIX}/profile`, method: 'GET' })
}

export function getCalendar(month?: string) {
  return request<CalendarMonth>({
    url: `${PREFIX}/calendar`,
    method: 'GET',
    params: month ? { month } : undefined,
  })
}

export function getDayDetail(date: string) {
  return request<CalendarDayDetail>({
    url: `${PREFIX}/days/${date}`,
    method: 'GET',
  })
}

export function getPayrollEstimate() {
  return request<PayrollEstimate>({
    url: `${PREFIX}/payroll-estimate`,
    method: 'GET',
  })
}

export function getAdjustments(month?: string) {
  return request<MeAdjustmentItem[]>({
    url: `${PREFIX}/adjustments`,
    method: 'GET',
    params: month ? { month } : undefined,
  })
}

export function getPlan() {
  return request<MePlan>({ url: `${PREFIX}/plan`, method: 'GET' })
}


export function getAdvanceLimit() {
  return request<AdvanceLimit>({
    url: `${PREFIX}/advance-limit`,
    method: 'GET',
  })
}

export function getAdvances() {
  return request<AdvanceDetail[]>({ url: `${PREFIX}/advances`, method: 'GET' })
}

export function createAdvance(data: CreateAdvancePayload) {
  return request<AdvanceDetail>({
    url: `${PREFIX}/advances`,
    method: 'POST',
    data,
  })
}

export function cancelAdvance(id: number) {
  return request<unknown>({
    url: `${PREFIX}/advances/${id}/cancel`,
    method: 'POST',
  })
}
