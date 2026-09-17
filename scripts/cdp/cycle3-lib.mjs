/**
 * Cycle 3 CDP 共用：②/③ 分栏、奖惩 sheet 对账、试算=正式、门槛互斥、选人 201+。
 * 禁止截图即绿；金标 / 排除 / 互斥硬拦 / #24 钩子不得 skip。
 * 侧栏泄漏不改断言（已知红）。不写产品 UI。
 *
 * 钩子（#24）：period-calc-run-success / period-calc-payrolls /
 *   period-calc-payroll-this-run-tag（不够绿） /
 *   period-calc-riders-unselected-all / period-calc-riders-truncated /
 *   period-export-adj-booked / period-export-adj-unbooked /
 *   period-export-adj-annotation / period-export-adj-sync-toggle /
 *   period-export-adj-sync-drop-count / period-export-adj-admit /
 *   trial-matches-official-calculate
 * 叠 Cycle 2 CDP（#21）+ Cycle 3 前端（#24）+ Cycle 3 后端（#23）。
 *
 * 具名：ops-calc-success-vs-existing / ops-export-adjustment-sheet /
 *   trial-equals-calc / ops-plan-threshold-xor / ops-calc-rider-picker-not-truncated
 */
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { apiFetch, authHeaders } from './cycle1-lib.mjs';
import {
  ATT_OVERTIME_NO,
  exportPeriodBlob,
  moneyEquals,
  parseIntText,
  xlsxText,
} from './cycle2-lib.mjs';

export const GOLD_C05B_GROSS = 4200;
export const GOLD_C05B_TOPUP = 0;
export const GOLD_C08_399 = 1995;
export const GOLD_C08_400 = 2400;
export const GOLD_C11_GROSS = 4890;
export const GOLD_C11_DAILY = 250;
export const GOLD_C05B_JOB = 'FIX_C05B_R1';
export const GOLD_C08_JOB_399 = 'FIX_C08_R399';
export const GOLD_C08_JOB_400 = 'FIX_C08_R400';
export const GOLD_C11_JOB = 'FIX_C11_R1';
export const PICKER_RIDER_201_JOB = 'FIX_C3_R201';

export const ADJ_POSTED_REMARK = 'FIX_C3_ADJ_POSTED';
export const ADJ_OPEN_REMARK = 'FIX_C3_ADJ_OPEN';
export const ADJ_ATT_REMARK = 'FIX_C3_ADJ_ATT';

export const RUN_SUCCESS_COPY = /本次成功/;
export const EXISTING_PAYROLL_COPY = /周期内已有薪资|已有薪资/;
export const ALL_RIDERS_COPY = /未选\s*=\s*计算本周期全部骑手/;
export const TRUNCATED_COPY = /仅列出前\s*\d+\s*人|其余请搜索/;
export const XOR_FAIL_COPY = /须互斥|互斥/;
export const XOR_DOUBLE_COPY = /双计/;
export const POSTED_ADJ_COPY = /已入账/;
export const OPEN_ADJ_COPY = /未入账/;
export const ATT_ADJ_MARK = /该骑手该日存在需关注订单|需关注同日同骑手/;
export const ADJ_DROP_COPY = /奖惩记录将少\s*\d+\s*条|将少\s*\d+\s*条/;
export const ADJ_ADMIT_COPY = /奖惩记录含与需关注同日同骑手/;
export const MODAL_SUBMIT_COPY = /已计算\s*\d+\s*名/;
export const CALC_MODAL_TITLE = '计算周期薪资';

export {
  apiFetch,
  authHeaders,
  exportPeriodBlob,
  moneyEquals,
  parseIntText,
  xlsxText,
};

export function trialGross(json) {
  const n = Number(json?.data?.summary?.gross ?? json?.data?.gross);
  return n;
}

export function calcGross(json) {
  const n = Number(
    json?.data?.gross ??
      json?.data?.summary?.gross ??
      json?.data?.payrolls?.[0]?.gross,
  );
  return n;
}

export function excludeFlagFromUrl(url, key) {
  try {
    const parsed = new URL(url);
    const raw = parsed.searchParams.get(key);
    if (raw == null) return null;
    return /^(1|true|yes)$/i.test(raw);
  } catch {
    return new RegExp(`${key}=(1|true)`, 'i').test(url);
  }
}

export async function exportPeriodBlobCycle3({
  apiUrl,
  token,
  periodId,
  excludeAttention,
  excludeAttentionAdjustments,
}) {
  const qs = new URLSearchParams();
  if (excludeAttention === true) qs.set('exclude_attention', 'true');
  if (excludeAttention === false) qs.set('exclude_attention', 'false');
  if (excludeAttentionAdjustments === true) {
    qs.set('exclude_attention_adjustments', 'true');
  }
  if (excludeAttentionAdjustments === false) {
    qs.set('exclude_attention_adjustments', 'false');
  }
  const suffix = qs.toString() ? `?${qs}` : '';
  const res = await fetch(`${apiUrl}/api/v1/rider-salary/periods/${periodId}/export${suffix}`, {
    headers: authHeaders(token),
  });
  const buf = Buffer.from(await res.arrayBuffer());
  return {
    res,
    buf,
    text: buf.toString('utf8'),
    attentionCount: res.headers.get('x-qipay-attention-count'),
    attentionExcluded: res.headers.get('x-qipay-attention-excluded'),
    adjBooked: res.headers.get('x-qipay-adjustment-booked'),
    adjUnbooked: res.headers.get('x-qipay-adjustment-unbooked'),
    adjAttention: res.headers.get('x-qipay-adjustment-attention'),
    adjExcluded: res.headers.get('x-qipay-adjustment-excluded'),
  };
}

export function xlsxSheetCells(buf, sheetName) {
  const raw = Buffer.isBuffer(buf) ? buf : Buffer.from(buf);
  const tmp = path.join(os.tmpdir(), `cdp-c3-export-${process.pid}-${Date.now()}.xlsx`);
  try {
    fs.writeFileSync(tmp, raw);
    return execFileSync(
      'python3',
      [
        '-c',
        [
          'import sys',
          'from openpyxl import load_workbook',
          'wb=load_workbook(sys.argv[1], data_only=True)',
          'name=sys.argv[2]',
          'if name not in wb.sheetnames:',
          '  print("SHEETS:"+("|".join(wb.sheetnames)))',
          '  raise SystemExit(0)',
          'ws=wb[name]',
          'for row in ws.iter_rows(values_only=True):',
          '  print("\\t".join("" if c is None else str(c) for c in row))',
        ].join('\n'),
        tmp,
        sheetName,
      ],
      { encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 },
    );
  } finally {
    try {
      fs.unlinkSync(tmp);
    } catch {
      /* ignore */
    }
  }
}

export function sheetHas(buf, sheetName, pattern) {
  const text = xlsxSheetCells(buf, sheetName);
  if (typeof pattern === 'string') return text.includes(pattern);
  return pattern.test(text);
}

export function c08Items(subjects, { overlap = false } = {}) {
  const commission = (subjects || []).find((row) => row.code === 'COMMISSION');
  if (!commission) throw new Error('C08 科目 COMMISSION 缺失');
  const lt = overlap ? '≤' : '<';
  return [
    {
      subject_id: commission.id,
      name: '门槛低于400',
      stage: 'period',
      sort_order: 10,
      condition_json: {
        逻辑: '且',
        条件: [{ 字段: '周期有效单量', 运算符: lt, 值: 400 }],
      },
      formula_json: { 类型: '字段乘单价', 字段: '周期有效单量', 单价: 5, 起算值: 0 },
      enabled: true,
    },
    {
      subject_id: commission.id,
      name: '门槛满400',
      stage: 'period',
      sort_order: 20,
      condition_json: {
        逻辑: '且',
        条件: [{ 字段: '周期有效单量', 运算符: '≥', 值: 400 }],
      },
      formula_json: { 类型: '字段乘单价', 字段: '周期有效单量', 单价: 6, 起算值: 0 },
      enabled: true,
    },
  ];
}

export function c11Items(subjects) {
  const unit = (subjects || []).find((row) => row.code === 'BASE_UNIT_PRICE');
  const rush =
    (subjects || []).find((row) => row.code === 'BONUS_ORDER_RUSH') ||
    (subjects || []).find((row) => row.code === 'BONUS_RUSH') ||
    unit;
  const salary = (subjects || []).find((row) => row.code === 'BASE_SALARY');
  if (!unit || !salary) throw new Error('C11 科目缺失');
  return [
    {
      subject_id: unit.id,
      name: '基础单价',
      stage: 'per_order',
      sort_order: 10,
      formula_json: { 类型: '固定金额', 金额: 4 },
      enabled: true,
    },
    {
      subject_id: rush.id,
      name: '冲单奖',
      stage: 'daily',
      sort_order: 20,
      condition_json: {
        逻辑: '且',
        条件: [{ 字段: '日有效单量', 运算符: '≥', 值: 30 }],
      },
      formula_json: { 类型: '固定金额', 金额: 50 },
      enabled: true,
    },
    {
      subject_id: salary.id,
      name: '底薪',
      stage: 'period',
      sort_order: 30,
      formula_json: { 类型: '表达式', 表达式: '2000 * 方案生效天数 / 周期天数' },
      enabled: true,
    },
  ];
}

export function assertNoSkipHttp(res, label) {
  if ([404, 405, 422, 501].includes(res.status)) {
    throw new Error(`${label} HTTP ${res.status}，不得 skip`);
  }
}

export async function fetchPeriodCalcRiders(apiUrl, token, periodId, { keyword, page, size } = {}) {
  const qs = new URLSearchParams();
  if (keyword) qs.set('keyword', keyword);
  qs.set('page', String(page || 1));
  qs.set('size', String(size || 200));
  const { res, json } = await apiFetch(
    apiUrl,
    token,
    'GET',
    `/api/v1/rider-salary/periods/${periodId}/calc-riders?${qs}`,
  );
  assertNoSkipHttp(res, `GET /periods/${periodId}/calc-riders`);
  return { res, json, data: json?.data };
}

export { ATT_OVERTIME_NO };
