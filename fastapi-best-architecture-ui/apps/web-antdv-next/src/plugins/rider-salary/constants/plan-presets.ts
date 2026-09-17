import type { PlanItemDraft } from '../types/plan';
import type { SubjectResult } from '../types/subject';

import { nextItemKey } from '../views/plan/helpers';

export interface PlanPresetItemDef {
  condition_json?: Record<string, unknown>;
  formula_json: Record<string, unknown>;
  name: string;
  remark?: string;
  stage: 'daily' | 'per_order' | 'period';
  subject_code: string;
}

export interface PlanPreset {
  category: string;
  description: string;
  expected?: string;
  id: string;
  items: PlanPresetItemDef[];
  mode_tag: string;
  name: string;
  tags: string[];
}

const nightCondition = {
  条件: [{ 值: ['22:00', '06:00'], 字段: '送达时刻', 运算符: '在时段内' }],
  逻辑: '且',
};

const baseSalaryExpr = (amount: number) => ({
  类型: '表达式',
  表达式: `${amount} * 方案生效天数 / 周期天数`,
});

const fixed = (amount: number) => ({ 类型: '固定金额', 金额: amount });

const fieldPrice = (field: string, price: number, start = 0) => ({
  字段: field,
  单价: price,
  起算值: start,
  类型: '字段乘单价',
});

const volumeLadder = (
  mode: '全量落档' | '分段累进',
  tiers: Array<[number, null | number, number]>,
  field = '周期有效单量',
) => ({
  字段: field,
  档位: tiers.map(([下限, 上限, 值]) => ({ 上限, 下限, 值 })),
  模式: mode,
  类型: '阶梯',
  计价: '按单价',
});

const volumeLadder465 = volumeLadder('全量落档', [
  [0, 400, 4],
  [400, 700, 5],
  [700, null, 6],
]);

const volumeLadder465Progressive = volumeLadder('分段累进', [
  [0, 400, 4],
  [400, 700, 5],
  [700, null, 6],
]);

const volumeLadder556 = volumeLadder('全量落档', [
  [0, 300, 5],
  [300, 700, 5.5],
  [700, null, 6],
]);

const volumeLadder556Progressive = volumeLadder('分段累进', [
  [0, 300, 5],
  [300, 700, 5.5],
  [700, null, 6],
]);

const distanceLadder = {
  字段: '配送距离',
  档位: [
    { 上限: 3, 下限: 0, 值: 0 },
    { 上限: 5, 下限: 3, 值: 1 },
    { 上限: 8, 下限: 5, 值: 2 },
    { 上限: null, 下限: 8, 值: 4 },
  ],
  模式: '全量落档',
  类型: '阶梯',
  计价: '固定金额',
};

const weightLadder = {
  字段: '商品重量',
  档位: [
    { 上限: 10, 下限: 0, 值: 0 },
    { 上限: 20, 下限: 10, 值: 1 },
    { 上限: null, 下限: 20, 值: 3 },
  ],
  模式: '全量落档',
  类型: '阶梯',
  计价: '固定金额',
};

export const PLAN_PRESET_CATEGORIES = [
  '基础模式',
  '底薪与保底',
  '单量阶梯',
  '多补贴叠加',
  '按日奖励',
  '字段对照',
] as const;

export const PLAN_PRESETS: PlanPreset[] = [
  {
    category: '基础模式',
    description: '众包兼职，每有效单固定 5 元，无底薪无阶梯。',
    expected: '100 单 → gross 500',
    id: 'C01',
    mode_tag: 'per_order',
    name: '纯按单（5 元/单）',
    tags: ['逐单', '最简单'],
    items: [
      {
        formula_json: fixed(5),
        name: '基础单价',
        stage: 'per_order',
        subject_code: 'BASE_UNIT_PRICE',
      },
    ],
  },
  {
    category: '底薪与保底',
    description: '逐单 4 元 + 夜间 2 元 + 周期底薪 2000 分摊。',
    expected: '700 单（夜间 18）→ gross 4836',
    id: 'C02',
    mode_tag: 'base_plus_commission',
    name: '底薪 + 逐单 + 夜间',
    tags: ['逐单', '周期', '夜间'],
    items: [
      {
        formula_json: fixed(4),
        name: '基础单价',
        stage: 'per_order',
        subject_code: 'BASE_UNIT_PRICE',
      },
      {
        condition_json: nightCondition,
        formula_json: fixed(2),
        name: '夜间补贴',
        stage: 'per_order',
        subject_code: 'BONUS_NIGHT',
      },
      {
        formula_json: baseSalaryExpr(2000),
        name: '底薪',
        stage: 'period',
        subject_code: 'BASE_SALARY',
      },
    ],
  },
  {
    category: '底薪与保底',
    description: '逐单 3 元 + 周期底薪 3000 + 整月单量全量落档提成（4/5/6 元/单）。',
    expected: '650 单 → gross 8200',
    id: 'C03',
    mode_tag: 'base_plus_commission',
    name: '底薪 + 单量阶梯（全量落档）',
    tags: ['底薪', '阶梯', '最常见'],
    items: [
      {
        formula_json: fixed(3),
        name: '基础单价',
        stage: 'per_order',
        subject_code: 'BASE_UNIT_PRICE',
      },
      {
        formula_json: baseSalaryExpr(3000),
        name: '底薪',
        stage: 'period',
        subject_code: 'BASE_SALARY',
      },
      {
        formula_json: volumeLadder465,
        name: '提成',
        remark: '字段=周期有效单量，全量落档',
        stage: 'period',
        subject_code: 'COMMISSION',
      },
    ],
  },
  {
    category: '底薪与保底',
    description: '同 C03，提成改为分段累进，超出部分才升档。',
    expected: '650 单 → gross 7800（比全量落档少 400）',
    id: 'C04',
    mode_tag: 'base_plus_commission',
    name: '底薪 + 单量阶梯（分段累进）',
    tags: ['底薪', '阶梯', '累进'],
    items: [
      {
        formula_json: fixed(3),
        name: '基础单价',
        stage: 'per_order',
        subject_code: 'BASE_UNIT_PRICE',
      },
      {
        formula_json: baseSalaryExpr(3000),
        name: '底薪',
        stage: 'period',
        subject_code: 'BASE_SALARY',
      },
      {
        formula_json: volumeLadder465Progressive,
        name: '提成',
        remark: '字段=周期有效单量，分段累进',
        stage: 'period',
        subject_code: 'COMMISSION',
      },
    ],
  },
  {
    category: '底薪与保底',
    description: '逐单 3.5 元 + 周期保底补足（3500 − 本期已计），补足项放最后。',
    expected: '800 单 → gross 3500；1200 单 → gross 4200',
    id: 'C05',
    mode_tag: 'guarantee_plus_commission',
    name: '保底 + 逐单提成',
    tags: ['保底', '逐单'],
    items: [
      {
        formula_json: fixed(3.5),
        name: '提成',
        stage: 'per_order',
        subject_code: 'COMMISSION',
      },
      {
        formula_json: {
          类型: '表达式',
          表达式: '最大值(0, 3500 - 本期已计金额)',
        },
        name: '保底补足',
        remark: 'sort 应晚于逐单，引用本期已计金额',
        stage: 'period',
        subject_code: 'GUARANTEE_TOPUP',
      },
    ],
  },
  {
    category: '单量阶梯',
    description: '无底薪无逐单，仅周期单量阶梯全量落档（5/5.5/6 元/单）。',
    expected: '420 单 → gross 2310',
    id: 'C06',
    mode_tag: 'commission',
    name: '纯单量阶梯（全量落档）',
    tags: ['阶梯', '无底薪'],
    items: [
      {
        formula_json: volumeLadder556,
        name: '提成',
        stage: 'period',
        subject_code: 'COMMISSION',
      },
    ],
  },
  {
    category: '单量阶梯',
    description: '无底薪，周期单量阶梯分段累进（5/5.5/6 元/单）。',
    expected: '420 单 → gross 2160',
    id: 'C07',
    mode_tag: 'commission',
    name: '纯单量阶梯（分段累进）',
    tags: ['阶梯', '累进'],
    items: [
      {
        formula_json: volumeLadder556Progressive,
        name: '提成',
        stage: 'period',
        subject_code: 'COMMISSION',
      },
    ],
  },
  {
    category: '单量阶梯',
    description: '未满 400 单整期 5 元/单，满 400 起整期 6 元/单（两条互斥周期项）。',
    expected: '399 单 → 1995；400 单 → 2400',
    id: 'C08',
    mode_tag: 'custom',
    name: '门槛换价（整期跳档）',
    tags: ['门槛', '周期'],
    items: [
      {
        condition_json: {
          条件: [{ 值: 400, 字段: '周期有效单量', 运算符: '<' }],
          逻辑: '且',
        },
        formula_json: fieldPrice('周期有效单量', 5),
        name: '提成（未达门槛）',
        stage: 'period',
        subject_code: 'COMMISSION',
      },
      {
        condition_json: {
          条件: [{ 值: 400, 字段: '周期有效单量', 运算符: '≥' }],
          逻辑: '且',
        },
        formula_json: fieldPrice('周期有效单量', 6),
        name: '提成（已达门槛）',
        stage: 'period',
        subject_code: 'COMMISSION',
      },
    ],
  },
  {
    category: '多补贴叠加',
    description: '每单 4 元基础 + 距离档补贴 + 重量档补贴，逐单叠加。',
    expected: '7.2km / 12 斤 → 7 元/单',
    id: 'C09',
    mode_tag: 'custom',
    name: '距离阶梯 + 重量阶梯 + 基础',
    tags: ['距离', '重量', '逐单'],
    items: [
      {
        formula_json: fixed(4),
        name: '基础单价',
        stage: 'per_order',
        subject_code: 'BASE_UNIT_PRICE',
      },
      {
        formula_json: distanceLadder,
        name: '距离补贴',
        stage: 'per_order',
        subject_code: 'BONUS_DISTANCE',
      },
      {
        formula_json: weightLadder,
        name: '超重补贴',
        stage: 'per_order',
        subject_code: 'BONUS_OVERWEIGHT',
      },
    ],
  },
  {
    category: '多补贴叠加',
    description: '基础 4 元 + 夜间 2 元 + 节假日 3 元，条件可叠加。',
    expected: '节假日夜间一单 → 9 元',
    id: 'C10',
    mode_tag: 'custom',
    name: '时段 + 节假日 + 基础',
    tags: ['夜间', '节假日'],
    items: [
      {
        formula_json: fixed(4),
        name: '基础单价',
        stage: 'per_order',
        subject_code: 'BASE_UNIT_PRICE',
      },
      {
        condition_json: nightCondition,
        formula_json: fixed(2),
        name: '夜间补贴',
        stage: 'per_order',
        subject_code: 'BONUS_NIGHT',
      },
      {
        condition_json: {
          条件: [{ 值: true, 字段: '是否节假日', 运算符: '=' }],
          逻辑: '且',
        },
        formula_json: fixed(3),
        name: '节假日补贴',
        stage: 'per_order',
        subject_code: 'BONUS_HOLIDAY',
      },
    ],
  },
  {
    category: '按日奖励',
    description: '逐单 4 元 + 日单≥30 奖 50 + 周期底薪 2000，三阶段同时使用。',
    expected: '660 单 / 5 天冲单 → gross 4890',
    id: 'C11',
    mode_tag: 'base_plus_commission',
    name: '按日冲单 + 底薪 + 逐单',
    tags: ['三阶段', '冲单奖'],
    items: [
      {
        formula_json: fixed(4),
        name: '基础单价',
        stage: 'per_order',
        subject_code: 'BASE_UNIT_PRICE',
      },
      {
        condition_json: {
          条件: [{ 值: 30, 字段: '日有效单量', 运算符: '≥' }],
          逻辑: '且',
        },
        formula_json: fixed(50),
        name: '冲单奖',
        stage: 'daily',
        subject_code: 'BONUS_ORDER_RUSH',
      },
      {
        formula_json: baseSalaryExpr(2000),
        name: '底薪',
        stage: 'period',
        subject_code: 'BASE_SALARY',
      },
    ],
  },
  {
    category: '按日奖励',
    description: '出勤日奖 10 元 + 周期单量阶梯全量落档（5/5.5/6）。',
    expected: '28 出勤 / 520 单 → gross 3140',
    id: 'C12',
    mode_tag: 'custom',
    name: '按日全勤 + 周期阶梯',
    tags: ['全勤', '阶梯'],
    items: [
      {
        condition_json: {
          条件: [{ 值: 1, 字段: '日有效单量', 运算符: '≥' }],
          逻辑: '且',
        },
        formula_json: fixed(10),
        name: '全勤奖',
        stage: 'daily',
        subject_code: 'BONUS_FULL_ATTEND',
      },
      {
        formula_json: volumeLadder556,
        name: '提成',
        stage: 'period',
        subject_code: 'COMMISSION',
      },
    ],
  },
  {
    category: '基础模式',
    description: '按配送距离 1.2 元/km 计提成，无底薪。',
    expected: '7.2 km → 8.64 元/单',
    id: 'C13',
    mode_tag: 'commission',
    name: '纯距离提成',
    tags: ['距离', '逐单'],
    items: [
      {
        formula_json: fieldPrice('配送距离', 1.2),
        name: '提成',
        stage: 'per_order',
        subject_code: 'COMMISSION',
      },
    ],
  },

  {
    category: '多补贴叠加',
    description: '基础 4 元 + 大额订单奖 + 超重补贴，逐单条件叠加。',
    expected: '120 元 / 25 斤 → 12 元/单',
    id: 'C15',
    mode_tag: 'custom',
    name: '大重量 / 大额订单奖',
    tags: ['大额', '超重'],
    items: [
      {
        formula_json: fixed(4),
        name: '基础单价',
        stage: 'per_order',
        subject_code: 'BASE_UNIT_PRICE',
      },
      {
        condition_json: {
          条件: [{ 值: 100, 字段: '订单金额', 运算符: '≥' }],
          逻辑: '且',
        },
        formula_json: fixed(5),
        name: '大额订单奖',
        stage: 'per_order',
        subject_code: 'BONUS_LARGE_ORDER',
      },
      {
        condition_json: {
          条件: [{ 值: 20, 字段: '商品重量', 运算符: '≥' }],
          逻辑: '且',
        },
        formula_json: fixed(3),
        name: '超重补贴',
        stage: 'per_order',
        subject_code: 'BONUS_OVERWEIGHT',
      },
    ],
  },
  {
    category: '按日奖励',
    description: '兼职低单价 6 元 + 日单≥15 奖 30 元，无周期项。',
    expected: '280 单 / 10 天达标 → gross 1980',
    id: 'C16',
    mode_tag: 'per_order',
    name: '兼职低单价 + 按日单量奖',
    tags: ['兼职', '按日'],
    items: [
      {
        formula_json: fixed(6),
        name: '基础单价',
        stage: 'per_order',
        subject_code: 'BASE_UNIT_PRICE',
      },
      {
        condition_json: {
          条件: [{ 值: 15, 字段: '日有效单量', 运算符: '≥' }],
          逻辑: '且',
        },
        formula_json: fixed(30),
        name: '日单量奖',
        stage: 'daily',
        subject_code: 'BONUS_ORDER_RUSH',
      },
    ],
  },
  {
    category: '字段对照',
    description: '同档位阶梯，字段改为「方案期内单量」，适用于月中换方案分段统计。',
    expected: '整月单方案勿误用；换方案段内 20 单 → 100',
    id: 'C17',
    mode_tag: 'commission',
    name: '方案期内单量阶梯（换方案用）',
    tags: ['字段对照', '换方案'],
    items: [
      {
        formula_json: volumeLadder(
          '全量落档',
          [
            [0, 300, 5],
            [300, 700, 5.5],
            [700, null, 6],
          ],
          '方案期内单量',
        ),
        name: '提成',
        remark: '月中换方案时用方案期内单量，勿与周期有效单量混用',
        stage: 'period',
        subject_code: 'COMMISSION',
      },
    ],
  },
];

export function resolveSubjectId(code: string, subjects: SubjectResult[]): number {
  return subjects.find((item) => item.code === code)?.id ?? 0;
}

export function buildItemsFromPreset(
  preset: PlanPreset,
  subjects: SubjectResult[],
): PlanItemDraft[] {
  const missing: string[] = [];
  const items = preset.items.map((item) => {
    const subject_id = resolveSubjectId(item.subject_code, subjects);
    if (!subject_id) missing.push(item.subject_code);
    return {
      _key: nextItemKey(),
      condition_json: item.condition_json ?? {},
      enabled: true,
      formula_json: item.formula_json,
      name: item.name,
      remark: item.remark ?? '',
      sort_order: 0,
      stage: item.stage,
      subject_id,
    };
  });
  if (missing.length > 0) {
    throw new Error(`缺少科目：${[...new Set(missing)].join('、')}`);
  }
  return items;
}

export function findPlanPreset(id: string): PlanPreset | undefined {
  return PLAN_PRESETS.find((item) => item.id === id);
}
