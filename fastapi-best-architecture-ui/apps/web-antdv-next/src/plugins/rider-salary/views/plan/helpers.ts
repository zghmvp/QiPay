import type {
  ConditionGroup,
  ConditionLeaf,
  FormulaKind,
  LadderTier,
  PlanItemDraft,
  PlanItemParam,
} from '../../types/plan';

import dayjs from 'dayjs';

let seq = 1;

export const PLAN_PRESET_COLORS = [
  '#1677ff',
  '#52c41a',
  '#faad14',
  '#f5222d',
  '#722ed1',
  '#13c2c2',
  '#eb2f96',
  '#fa8c16',
  '#2f54eb',
  '#a0d911',
  '#08979c',
  '#cf1322',
];

export const COLOR_PRESETS = [
  { colors: PLAN_PRESET_COLORS, label: '常用色板' },
];

export const STAGE_ORDER = ['per_order', 'daily', 'period'] as const;

export const OPERATORS_BY_TYPE: Record<string, string[]> = {
  bool: ['='],
  date: ['=', '>', '<', '在区间内'],
  enum: ['=', '≠', '属于', '不属于'],
  number: ['=', '≠', '>', '≥', '<', '≤', '在区间内', '不在区间内'],
  time: ['在时段内', '不在时段内', '>', '<'],
};

export const FIELD_GROUPS = [
  {
    label: '订单',
    names: [
      '配送距离',
      '商品重量',
      '订单金额',
      '下单时刻',
      '送达时刻',
      '配送时长',
      '订单状态',
    ],
  },
  {
    label: '日期',
    names: [
      '日期',
      '星期',
      '是否节假日',
      '是否周末',
    ],
  },
  {
    label: '聚合',
    names: [
      '日单量',
      '日总单量',
      '日有效单量',
      '日逐单金额',
      '周期单量',
      '周期总单量',
      '周期有效单量',
      '方案期内单量',
      '周期天数',
      '方案生效天数',
      '出勤天数',
      '本期已计金额',
      '本期逐单金额',
      '本期手工奖',
      '本期手工惩',
    ],
  },
  {
    label: '骑手',
    names: ['用工类型', '工龄月数', '入职天数'],
  },
];

export const RANGE_OPERATORS = new Set([
  '不在区间内',
  '不在时段内',
  '在区间内',
  '在时段内',
]);

export const MULTI_OPERATORS = new Set(['不属于', '属于']);

export function nextItemKey() {
  seq += 1;
  return `item-${Date.now()}-${seq}`;
}

export function emptyGroup(logic: ConditionGroup['逻辑'] = '且'): ConditionGroup {
  return { 条件: [], 逻辑: logic };
}

export function isGroup(
  node: ConditionGroup | ConditionLeaf | null | undefined,
): node is ConditionGroup {
  return !!node && typeof node === 'object' && '逻辑' in node;
}

export function isLeaf(
  node: ConditionGroup | ConditionLeaf | null | undefined,
): node is ConditionLeaf {
  return !!node && typeof node === 'object' && !('逻辑' in node);
}

export function fromConditionJson(
  json: null | Record<string, unknown> | undefined,
): ConditionGroup {
  if (!json || Object.keys(json).length === 0) return emptyGroup();
  if ('逻辑' in json) return json as unknown as ConditionGroup;
  if ('字段' in json) return { 条件: [json as unknown as ConditionLeaf], 逻辑: '且' };
  return emptyGroup();
}

function sanitizeNode(
  node: ConditionGroup | ConditionLeaf,
): ConditionGroup | ConditionLeaf | null {
  if (isGroup(node)) {
    const children = node.条件
      .map((child) => sanitizeNode(child))
      .filter((child): child is ConditionGroup | ConditionLeaf => child !== null);
    if (children.length === 0) return null;
    return { 条件: children, 逻辑: node.逻辑 };
  }
  if (!node.字段 || !node.运算符) return null;
  return node;
}

export function toConditionJson(
  group: ConditionGroup | null | undefined,
): null | Record<string, unknown> {
  if (!group) return {};
  const clean = sanitizeNode(group);
  if (!clean || !isGroup(clean)) return {};
  return clean as unknown as Record<string, unknown>;
}

export function lastNaturalMonth(): [string, string] {
  const start = dayjs().subtract(1, 'month').startOf('month');
  return [start.format('YYYY-MM-DD'), start.endOf('month').format('YYYY-MM-DD')];
}

export function defaultFormula(kind: FormulaKind): Record<string, unknown> {
  if (kind === '固定金额') return { 类型: '固定金额', 金额: 2 };
  if (kind === '字段乘单价') {
    return { 类型: '字段乘单价', 单价: 0.8, 字段: '配送距离', 起算值: 0 };
  }
  if (kind === '阶梯') {
    return {
      类型: '阶梯',
      字段: '配送距离',
      模式: '全量落档',
      计价: '固定金额',
      档位: [
        { 上限: 3, 下限: 0, 值: 1 },
        { 上限: 5, 下限: 3, 值: 2 },
        { 上限: null, 下限: 5, 值: 3 },
      ] satisfies LadderTier[],
    };
  }
  return { 类型: '表达式', 表达式: '' };
}

export function formulaKindOf(
  json: null | Record<string, unknown> | undefined,
): FormulaKind {
  const kind = json?.类型;
  if (kind === '字段乘单价' || kind === '阶梯' || kind === '表达式') return kind;
  return '固定金额';
}

export function createDraftItem(stage = 'per_order'): PlanItemDraft {
  return {
    _key: nextItemKey(),
    condition_json: {},
    enabled: true,
    formula_json: defaultFormula('固定金额'),
    name: '新方案项',
    remark: '',
    sort_order: 0,
    stage,
    subject_id: 0,
  };
}

export function toDraftItems(items: PlanItemParam[]): PlanItemDraft[] {
  return items.map((item, index) => ({
    ...item,
    _key: nextItemKey(),
    sort_order: item.sort_order ?? index,
    subject_id: item.subject_id,
  }));
}

export function toSaveItems(items: PlanItemDraft[]): PlanItemParam[] {
  const grouped = STAGE_ORDER.flatMap((stage) =>
    items.filter((item) => item.stage === stage),
  );
  return grouped.map((item, index) => ({
    condition_json: toConditionJson(fromConditionJson(item.condition_json)),
    enabled: item.enabled,
    formula_json: item.formula_json ?? defaultFormula('固定金额'),
    name: item.name,
    remark: item.remark || null,
    sort_order: index,
    stage: item.stage,
    subject_id: item.subject_id,
  }));
}

export function summarizeCondition(
  json: null | Record<string, unknown> | undefined,
  compiled?: null | string,
): string {
  if (compiled && compiled !== 'True') return compiled;
  const group = fromConditionJson(json);
  if (group.条件.length === 0) return '恒真（空条件）';
  return group.条件
    .map((node) => {
      if (isGroup(node)) {
        const inner = node.条件
          .map((child) =>
            isLeaf(child)
              ? `${child.字段 ?? ''} ${child.运算符 ?? ''} ${formatValue(child.值)}`
              : '…',
          )
          .join(` ${node.逻辑} `);
        return `(${inner})`;
      }
      return `${node.字段 ?? ''} ${node.运算符 ?? ''} ${formatValue(node.值)}`;
    })
    .join(` ${group.逻辑} `);
}

export function summarizeFormula(
  json: null | Record<string, unknown> | undefined,
  compiled?: null | string,
): string {
  if (compiled) return compiled;
  if (!json) return '—';
  const kind = formulaKindOf(json);
  if (kind === '固定金额') return `固定金额 ${json.金额 ?? ''}`;
  if (kind === '字段乘单价') {
    return `(${json.字段 ?? ''} − ${json.起算值 ?? 0}) × ${json.单价 ?? ''}`;
  }
  if (kind === '阶梯') {
    return `阶梯 ${json.字段 ?? ''} / ${json.模式 ?? ''} / ${json.计价 ?? ''}`;
  }
  return String(json.表达式 || '表达式');
}

/** 方案项一句话说明：接口 summary / 备注优先，否则条件+公式摘要 */
export function summarizeItem(item: {
  condition_expr?: null | string;
  condition_json?: null | Record<string, unknown>;
  formula_expr?: null | string;
  formula_json?: null | Record<string, unknown>;
  remark?: null | string;
  summary?: null | string;
}): string {
  const fromApi = item.summary?.trim();
  if (fromApi) return fromApi;
  const remark = item.remark?.trim();
  if (remark) return remark;
  const cond = summarizeCondition(item.condition_json, item.condition_expr);
  const formula = summarizeFormula(item.formula_json, item.formula_expr);
  const parts: string[] = [];
  if (cond && cond !== '恒真（空条件）' && cond !== 'True') {
    parts.push(`条件 ${cond}`);
  }
  if (formula && formula !== '—') {
    parts.push(formula);
  }
  return parts.join('；') || '—';
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (Array.isArray(value)) return value.join('~');
  if (typeof value === 'boolean') return value ? '是' : '否';
  return String(value);
}

export function canEditVersion(status?: string, isUsed?: boolean) {
  return status === 'draft' && !isUsed;
}

export function trialLabel(options: {
  dirty?: boolean;
  itemsHash?: null | string;
  trialHash?: null | string;
  trialPassed?: boolean;
}) {
  if (options.dirty) return { color: 'warning', text: '需重新试算' };
  if (options.trialPassed && options.trialHash && options.trialHash === options.itemsHash) {
    return { color: 'success', text: '试算通过 ✓' };
  }
  if (options.trialPassed && options.trialHash && options.trialHash !== options.itemsHash) {
    return { color: 'warning', text: '需重新试算' };
  }
  if (options.trialHash && !options.trialPassed) {
    return { color: 'error', text: '试算未通过' };
  }
  return { color: 'default', text: '未试算' };
}

export function activateHint(options: {
  dirty?: boolean;
  itemsHash?: null | string;
  trialHash?: null | string;
  trialPassed?: boolean;
}) {
  if (options.dirty) return '请先保存方案项';
  if (!options.trialPassed) return '请先完成试算再启用';
  if (options.trialHash !== options.itemsHash) return '方案内容已变更，请重新试算';
  return '';
}

/** 保底/补足类：引用「本期已计金额」或名称含保底，须排在周期阶段最后 */
export function isGuaranteeLikeItem(item: {
  formula_expr?: null | string;
  formula_json?: null | Record<string, unknown>;
  name?: string;
  stage?: string;
}): boolean {
  if (item.stage && item.stage !== 'period') return false;
  const name = item.name || '';
  if (/保底|补足|补差/.test(name)) return true;
  const expr =
    item.formula_expr ||
    (item.formula_json && typeof item.formula_json.表达式 === 'string'
      ? String(item.formula_json.表达式)
      : '') ||
    JSON.stringify(item.formula_json || {});
  return expr.includes('本期已计金额');
}

export function findMisplacedGuaranteeKeys(items: PlanItemDraft[]): string[] {
  const period = items.filter((item) => item.stage === 'period' && item.enabled !== false);
  if (period.length === 0) return [];
  const misplaced: string[] = [];
  period.forEach((item, index) => {
    if (isGuaranteeLikeItem(item) && index !== period.length - 1) {
      misplaced.push(item._key);
    }
  });
  return misplaced;
}

/** 将保底类周期项沉到周期阶段末尾，保持其他阶段顺序 */
export function sinkGuaranteeItems(items: PlanItemDraft[]): PlanItemDraft[] {
  const period = items.filter((item) => item.stage === 'period');
  const others = items.filter((item) => item.stage !== 'period');
  const guarantees = period.filter((item) => isGuaranteeLikeItem(item));
  const nonGuarantees = period.filter((item) => !isGuaranteeLikeItem(item));
  const nextPeriod = [...nonGuarantees, ...guarantees];
  return STAGE_ORDER.flatMap((stage) =>
    stage === 'period' ? nextPeriod : others.filter((item) => item.stage === stage),
  );
}

export function defaultOperatorForType(type?: string) {
  return OPERATORS_BY_TYPE[type || 'number']?.[0] ?? '=';
}

export function defaultValueFor(type?: string, operator?: string): unknown {
  if (operator && RANGE_OPERATORS.has(operator)) {
    return type === 'time' ? [undefined, undefined] : [undefined, undefined];
  }
  if (operator && MULTI_OPERATORS.has(operator)) return [];
  if (type === 'bool') return true;
  return undefined;
}
