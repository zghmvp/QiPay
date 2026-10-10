// 插件单测（不改框架 vitest 配置）。在 fastapi-best-architecture-ui 目录执行：
// pnpm exec vitest run apps/web-antdv-next/src/plugins/rider-salary
import type { PlanItemDraft } from '../../types/plan';

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  accruedSortHint,
  activateHint,
  applyBaseSalaryTemplate,
  canEditVersion,
  createDraftItem,
  defaultFormula,
  defaultOperatorForType,
  defaultValueFor,
  emptyGroup,
  formulaKindOf,
  fromConditionJson,
  isGroup,
  isLeaf,
  itemReferencesAccrued,
  lastNaturalMonth,
  moveAccruedItemsLast,
  newPlanEditorLocation,
  operatorsForFieldType,
  planEditorVersionId,
  readUnsavedPlanDraft,
  shouldTrialWithoutSaving,
  summarizeCondition,
  summarizeFormula,
  canonicalItemsJson,
  emptyPlanItemsHash,
  ILLEGAL_LADDER_MESSAGE,
  isIllegalLadderCombo,
  isIllegalLadderFormula,
  isPlanItemsDirty,
  itemsHashOf,
  ladderModeDisabled,
  ladderPricingDisabled,
  planItemsHash,
  toConditionJson,
  toDraftItems,
  toSaveItems,
  trialLabel,
  UNSAVED_PLAN_LEAVE_MESSAGE,
  unreplacedPlaceholderLabels,
} from './helpers';

const GUARANTEE = { 类型: '表达式', 表达式: '最大值(0, 3500 - 本期已计金额)' };
const FIXED = { 类型: '固定金额', 金额: 10 };

function draft(
  partial: Partial<PlanItemDraft> & Pick<PlanItemDraft, 'name' | 'stage'>,
): PlanItemDraft {
  return {
    _key: partial.name,
    condition_json: {},
    enabled: true,
    formula_json: FIXED,
    remark: '',
    sort_order: 0,
    subject_id: 1,
    ...partial,
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe('条件拼装', () => {
  it('空条件、叶子和分组互相识别', () => {
    const group = emptyGroup('或');
    const leaf = { 值: true, 字段: '是否高温', 运算符: '=' };

    expect(group).toEqual({ 条件: [], 逻辑: '或' });
    expect(isGroup(group)).toBe(true);
    expect(isLeaf(group)).toBe(false);
    expect(isGroup(leaf)).toBe(false);
    expect(isLeaf(leaf)).toBe(true);
    expect(isGroup(null)).toBe(false);
    expect(isLeaf(undefined)).toBe(false);
  });

  it('裸叶子包进「且」，空对象和残缺节点回落成空组', () => {
    expect(fromConditionJson(null)).toEqual({ 条件: [], 逻辑: '且' });
    expect(fromConditionJson({})).toEqual({ 条件: [], 逻辑: '且' });
    expect(fromConditionJson({ 无关: 1 })).toEqual({ 条件: [], 逻辑: '且' });
    expect(
      fromConditionJson({ 值: '六', 字段: '星期', 运算符: '=' }),
    ).toEqual({
      条件: [{ 值: '六', 字段: '星期', 运算符: '=' }],
      逻辑: '且',
    });
    expect(
      fromConditionJson({
        条件: [{ 值: 1, 字段: '日单量', 运算符: '>' }],
        逻辑: '或',
      }),
    ).toEqual({
      条件: [{ 值: 1, 字段: '日单量', 运算符: '>' }],
      逻辑: '或',
    });
  });

  it('保存前丢掉没写完的叶子和空组，保留有效嵌套', () => {
    const cleaned = toConditionJson({
      条件: [
        { 值: true, 字段: '是否高温', 运算符: '=' },
        { 字段: '日期' },
        { 条件: [], 逻辑: '或' },
        {
          条件: [{ 值: '六', 字段: '星期', 运算符: '=' }],
          逻辑: '或',
        },
      ],
      逻辑: '且',
    });

    expect(cleaned).toEqual({
      条件: [
        { 值: true, 字段: '是否高温', 运算符: '=' },
        {
          条件: [{ 值: '六', 字段: '星期', 运算符: '=' }],
          逻辑: '或',
        },
      ],
      逻辑: '且',
    });
    expect(toConditionJson(emptyGroup())).toEqual({});
    expect(toConditionJson(null)).toEqual({});
  });

  it('摘要展开布尔、区间和嵌套，编译结果优先，True 仍回落到条件', () => {
    const json = {
      条件: [
        { 值: true, 字段: '是否高温', 运算符: '=' },
        { 值: false, 字段: '是否周末', 运算符: '=' },
        { 值: [1, 3], 字段: '配送距离', 运算符: '在区间内' },
        {
          条件: [
            { 值: '六', 字段: '星期', 运算符: '=' },
            { 值: '日', 字段: '星期', 运算符: '=' },
          ],
          逻辑: '或',
        },
      ],
      逻辑: '且',
    };

    expect(summarizeCondition(json)).toBe(
      '是否高温 = 是 且 是否周末 = 否 且 配送距离 在区间内 1~3 且 (星期 = 六 或 星期 = 日)',
    );
    expect(summarizeCondition({})).toBe('恒真（空条件）');
    expect(summarizeCondition(json, '是否高温 == True')).toBe('是否高温 == True');
    expect(summarizeCondition(json, 'True')).toBe(
      '是否高温 = 是 且 是否周末 = 否 且 配送距离 在区间内 1~3 且 (星期 = 六 或 星期 = 日)',
    );
  });

  it('按字段类型给默认运算符和默认值', () => {
    const operators = {
      bool: ['=', '≠'],
      date: ['=', '≠', '>', '≥', '<', '≤', '在区间内'],
      enum: ['=', '≠', '属于', '不属于'],
      number: ['=', '≠', '>', '≥', '<', '≤', '在区间内', '不在区间内'],
      time: ['=', '≠', '在时段内'],
    };
    expect(operatorsForFieldType('bool', operators)).toEqual(['=', '≠']);
    expect(operatorsForFieldType('time', operators)).toEqual([
      '=',
      '≠',
      '在时段内',
    ]);
    expect(operatorsForFieldType('date', operators)).toContain('≥');
    expect(operatorsForFieldType('time')).toEqual(['=']);
    expect(defaultOperatorForType('time', operators)).toBe('=');
    expect(defaultOperatorForType('enum', operators)).toBe('=');
    expect(defaultOperatorForType('date', operators)).toBe('=');
    expect(defaultOperatorForType()).toBe('=');
    expect(defaultOperatorForType('unknown')).toBe('=');

    expect(defaultValueFor('bool', '=')).toBe(true);
    expect(defaultValueFor('number', '属于')).toEqual([]);
    expect(defaultValueFor('enum', '不属于')).toEqual([]);
    expect(defaultValueFor('number', '在区间内')).toEqual([
      undefined,
      undefined,
    ]);
    expect(defaultValueFor('time', '不在时段内')).toEqual([
      undefined,
      undefined,
    ]);
    expect(defaultValueFor('number', '>')).toBeUndefined();
  });
});

describe('公式拼装', () => {
  it('四种公式的默认值和类型识别', () => {
    expect(defaultFormula('固定金额')).toEqual({ 类型: '固定金额', 金额: 2 });
    expect(defaultFormula('字段乘单价')).toEqual({
      类型: '字段乘单价',
      单价: 0.8,
      字段: '配送距离',
      起算值: 0,
    });
    expect(defaultFormula('阶梯')).toEqual({
      类型: '阶梯',
      字段: '配送距离',
      模式: '全量落档',
      计价: '固定金额',
      档位: [
        { 上限: 3, 下限: 0, 值: 1 },
        { 上限: 5, 下限: 3, 值: 2 },
        { 上限: null, 下限: 5, 值: 3 },
      ],
    });
    expect(defaultFormula('表达式')).toEqual({ 类型: '表达式', 表达式: '' });

    expect(formulaKindOf({ 类型: '阶梯' })).toBe('阶梯');
    expect(formulaKindOf({ 类型: '字段乘单价' })).toBe('字段乘单价');
    expect(formulaKindOf({ 类型: '表达式' })).toBe('表达式');
    expect(formulaKindOf(null)).toBe('固定金额');
    expect(formulaKindOf({ 类型: '未知' })).toBe('固定金额');
  });

  it('摘要覆盖四种公式，编译串优先，金额 0 不丢', () => {
    expect(summarizeFormula({ 类型: '固定金额', 金额: 0 })).toBe('固定金额 0');
    expect(summarizeFormula(defaultFormula('字段乘单价'))).toBe(
      '(配送距离 − 0) × 0.8',
    );
    expect(
      summarizeFormula({
        类型: '阶梯',
        字段: '周期单量',
        模式: '增量累进',
        计价: '单价',
      }),
    ).toBe('阶梯 周期单量 / 增量累进 / 单价');
    expect(summarizeFormula({ 类型: '表达式', 表达式: '' })).toBe('表达式');
    expect(summarizeFormula({ 类型: '表达式', 表达式: '周期单量 * 5' })).toBe(
      '周期单量 * 5',
    );
    expect(summarizeFormula(null)).toBe('—');
    expect(summarizeFormula(GUARANTEE, 'max(0, 3500 - accrued)')).toBe(
      'max(0, 3500 - accrued)',
    );
  });

  it('新建草稿项使用固定金额，保存时按阶段重排并重编号', () => {
    const created = createDraftItem();
    const another = createDraftItem('daily');
    expect(created.name).toBe('新方案项');
    expect(created.stage).toBe('per_order');
    expect(created.enabled).toBe(true);
    expect(created.formula_json).toEqual(defaultFormula('固定金额'));
    expect(created.condition_json).toEqual({});
    expect(another.stage).toBe('daily');
    expect(created._key).not.toBe(another._key);

    const saved = toSaveItems([
      draft({
        name: '周期奖',
        remark: '',
        sort_order: 1,
        stage: 'period',
        formula_json: null,
        condition_json: {
          条件: [{ 字段: '日期' }, { 值: 1, 字段: '周期单量', 运算符: '>' }],
          逻辑: '且',
        },
      }),
      draft({ name: '逐单B', sort_order: 9, stage: 'per_order' }),
      draft({ name: '逐单A', sort_order: 1, stage: 'per_order' }),
      draft({ name: '日奖', remark: '备注', sort_order: 5, stage: 'daily' }),
    ]);

    expect(saved.map((item) => [item.name, item.stage, item.sort_order])).toEqual([
      ['逐单B', 'per_order', 0],
      ['逐单A', 'per_order', 1],
      ['日奖', 'daily', 2],
      ['周期奖', 'period', 3],
    ]);
    expect(saved[2]?.remark).toBe('备注');
    expect(saved[3]?.remark).toBeNull();
    expect(saved[3]?.formula_json).toEqual(defaultFormula('固定金额'));
    expect(saved[3]?.condition_json).toEqual({
      条件: [{ 值: 1, 字段: '周期单量', 运算符: '>' }],
      逻辑: '且',
    });
  });

  it('读回方案项时补 key，缺省顺序用下标', () => {
    const drafts = toDraftItems([
      {
        condition_json: {},
        enabled: true,
        formula_json: FIXED,
        name: '有序',
        remark: null,
        sort_order: 4,
        stage: 'per_order',
        subject_id: 2,
      },
      {
        condition_json: {},
        enabled: false,
        formula_json: FIXED,
        name: '缺序',
        remark: null,
        sort_order: undefined as unknown as number,
        stage: 'daily',
        subject_id: 3,
      },
    ]);
    expect(drafts.map((item) => item.sort_order)).toEqual([4, 1]);
    expect(drafts[0]?._key).toBeTruthy();
    expect(drafts[0]?._key).not.toBe(drafts[1]?._key);
    expect(drafts[1]?.subject_id).toBe(3);
  });
});

describe('本期已计金额排序', () => {
  it('方案编辑器写明保底不含手工奖惩', () => {
    const source = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), 'components/FormulaBuilder.vue'),
      'utf8',
    );
    expect(source).toContain('保底不含手工奖惩');
  });

  it('公式字段、阶梯字段、表达式和条件都能认出引用', () => {
    expect(itemReferencesAccrued({ formula_json: GUARANTEE })).toBe(true);
    expect(
      itemReferencesAccrued({
        formula_json: { 类型: '字段乘单价', 单价: 1, 字段: '本期已计金额' },
      }),
    ).toBe(true);
    expect(
      itemReferencesAccrued({
        formula_json: { 类型: '阶梯', 字段: '本期已计金额', 档位: [] },
      }),
    ).toBe(true);
    expect(
      itemReferencesAccrued({
        condition_json: {
          条件: [{ 值: 1000, 字段: '本期已计金额', 运算符: '>' }],
          逻辑: '且',
        },
      }),
    ).toBe(true);
    expect(
      itemReferencesAccrued({
        formula_json: { 类型: '表达式', 表达式: '周期有效单量 * 5' },
      }),
    ).toBe(false);
    expect(
      itemReferencesAccrued({
        formula_json: { 类型: '表达式', 表达式: '本期已计金额外 * 1' },
      }),
    ).toBe(false);
    expect(
      itemReferencesAccrued({
        formula_json: { 类型: '表达式', 表达式: '"本期已计金额"' },
      }),
    ).toBe(false);
    expect(itemReferencesAccrued({ formula_json: FIXED })).toBe(false);
  });

  it('保底项不在周期阶段最后时给出提示，已在最后或未启用则不提示', () => {
    const misordered = [
      draft({ name: '提成', stage: 'per_order', formula_json: { 类型: '固定金额', 金额: 3.5 } }),
      draft({ name: '保底补足', stage: 'period', formula_json: GUARANTEE }),
      draft({ name: '全勤奖', stage: 'period' }),
    ];
    expect(accruedSortHint(misordered)).toBe(
      '保底项「保底补足」引用「本期已计金额」，必须排在周期阶段最后，否则补差会偏大',
    );

    expect(
      accruedSortHint([
        draft({ name: '全勤奖', stage: 'period' }),
        draft({ name: '保底补足', stage: 'period', formula_json: GUARANTEE }),
        draft({ name: '基础单价', stage: 'per_order' }),
      ]),
    ).toBe('');

    expect(
      accruedSortHint([
        draft({
          enabled: false,
          name: '保底补足',
          stage: 'period',
          formula_json: GUARANTEE,
        }),
        draft({ name: '全勤奖', stage: 'period' }),
      ]),
    ).toBe('');

    expect(
      accruedSortHint([
        draft({ name: '保底补足', stage: 'period', formula_json: GUARANTEE }),
        draft({ enabled: false, name: '全勤奖', stage: 'period' }),
      ]),
    ).toBe('');

    expect(
      accruedSortHint([
        draft({ name: '错阶段', stage: 'per_order', formula_json: GUARANTEE }),
      ]),
    ).toBe('');

    expect(accruedSortHint([])).toBe('');
  });

  it('条件引用同样必须排在最后，空名称显示为未命名', () => {
    expect(
      accruedSortHint([
        draft({
          condition_json: {
            条件: [{ 值: 1000, 字段: '本期已计金额', 运算符: '>' }],
            逻辑: '且',
          },
          name: '门槛',
          stage: 'period',
        }),
        draft({ name: '全勤奖', stage: 'period' }),
      ]),
    ).toBe(
      '保底项「门槛」引用「本期已计金额」，必须排在周期阶段最后，否则补差会偏大',
    );

    expect(
      accruedSortHint([
        draft({ name: '   ', stage: 'period', formula_json: GUARANTEE }),
        draft({ name: '全勤奖', stage: 'period' }),
      ]),
    ).toContain('「未命名」');
  });

  it('两项都引用时，只有没排到最后的那项出现在提示里', () => {
    expect(
      accruedSortHint([
        draft({ _key: 'a', name: '保底甲', stage: 'period', formula_json: GUARANTEE }),
        draft({ _key: 'b', name: '保底乙', stage: 'period', formula_json: GUARANTEE }),
      ]),
    ).toBe(
      '保底项「保底甲」引用「本期已计金额」，必须排在周期阶段最后，否则补差会偏大',
    );
  });

  it('移到最后只搬启用的周期引用项，并保持原对象', () => {
    const perOrder = draft({ _key: 'po', name: '提成', stage: 'per_order' });
    const guarantee = draft({
      _key: 'g',
      name: '保底补足',
      stage: 'period',
      formula_json: GUARANTEE,
    });
    const attendance = draft({ _key: 'at', name: '全勤奖', stage: 'period' });
    const source = [perOrder, guarantee, attendance];

    const moved = moveAccruedItemsLast(source);

    expect(moved.map((item) => item.name)).toEqual(['提成', '全勤奖', '保底补足']);
    expect(moved[0]).toBe(perOrder);
    expect(moved[1]).toBe(attendance);
    expect(moved[2]).toBe(guarantee);
    expect(source.map((item) => item.name)).toEqual(['提成', '保底补足', '全勤奖']);
    expect(accruedSortHint(moved)).toBe('');
  });

  it('没有可搬的项时返回原数组；周期项全是引用时按阶段归位', () => {
    const plain = [draft({ name: '全勤奖', stage: 'period' })];
    expect(moveAccruedItemsLast(plain)).toBe(plain);

    const daily = draft({ _key: 'd', name: '日奖', stage: 'daily' });
    const first = draft({
      _key: 'a',
      name: '保底甲',
      stage: 'period',
      formula_json: GUARANTEE,
    });
    const second = draft({
      _key: 'b',
      name: '保底乙',
      stage: 'period',
      formula_json: GUARANTEE,
    });
    const regrouped = moveAccruedItemsLast([first, daily, second]);
    expect(regrouped.map((item) => item.name)).toEqual(['日奖', '保底甲', '保底乙']);
    expect(accruedSortHint(regrouped)).toBe(
      '保底项「保底甲」引用「本期已计金额」，必须排在周期阶段最后，否则补差会偏大',
    );
  });

  it('停用的引用项留在原地，已启用的引用项挪到周期项末尾', () => {
    const disabled = draft({
      _key: 'off',
      enabled: false,
      name: '旧保底',
      stage: 'period',
      formula_json: GUARANTEE,
    });
    const attendance = draft({ _key: 'at', name: '全勤奖', stage: 'period' });
    const current = draft({
      _key: 'on',
      name: '保底补足',
      stage: 'period',
      formula_json: GUARANTEE,
    });
    expect(moveAccruedItemsLast([disabled, current, attendance]).map((item) => item._key)).toEqual([
      'off',
      'at',
      'on',
    ]);
  });
});

describe('试算与可编辑', () => {
  it('试算标签按脏数据、哈希和通过状态分支', () => {
    expect(trialLabel({ dirty: true, itemsHash: 'a', trialHash: 'a', trialPassed: true })).toEqual({
      color: 'warning',
      text: '需重新试算',
    });
    expect(trialLabel({ itemsHash: 'a', trialHash: 'a', trialPassed: true })).toEqual({
      color: 'success',
      text: '试算通过 ✓',
    });
    expect(trialLabel({ itemsHash: 'b', trialHash: 'a', trialPassed: true })).toEqual({
      color: 'warning',
      text: '需重新试算',
    });
    expect(trialLabel({ trialHash: 'a', trialPassed: false })).toEqual({
      color: 'error',
      text: '试算未通过',
    });
    expect(trialLabel({ trialPassed: true })).toEqual({
      color: 'default',
      text: '未试算',
    });
  });

  it('启用前提示先看未保存，再看是否试算，最后看哈希', () => {
    expect(activateHint({ dirty: true, itemsHash: 'a', trialHash: 'a', trialPassed: true })).toBe(
      '请先保存方案项',
    );
    expect(activateHint({ itemsHash: 'b', trialHash: 'a', trialPassed: false })).toBe(
      '请先完成试算再启用',
    );
    expect(activateHint({ itemsHash: 'b', trialHash: 'a', trialPassed: true })).toBe(
      '方案内容已变更，请重新试算',
    );
    expect(activateHint({ itemsHash: 'a', trialHash: 'a', trialPassed: true })).toBe('');
  });

  it('未保存草稿和改过的方案走不落库试算', () => {
    expect(planEditorVersionId('new')).toBe(0);
    expect(planEditorVersionId('12')).toBe(12);
    expect(planEditorVersionId(0)).toBe(0);
    expect(planEditorVersionId('12.5')).toBe(0);
    expect(shouldTrialWithoutSaving(0, false)).toBe(true);
    expect(shouldTrialWithoutSaving(8, true)).toBe(true);
    expect(shouldTrialWithoutSaving(8, false)).toBe(false);
    expect(newPlanEditorLocation(3)).toEqual({
      path: '/rider-salary/plan/editor/new',
      query: { plan_id: '3' },
    });
    expect(
      readUnsavedPlanDraft({
        draftItemsJson: JSON.stringify([{ name: '基础单价', subject_id: 1 }]),
        modeTag: 'per_order',
      }),
    ).toEqual({
      draftItems: [{ name: '基础单价', subject_id: 1 }],
      modeTag: 'per_order',
    });
    expect(readUnsavedPlanDraft({ draftItemsJson: '{' })).toEqual({
      draftItems: undefined,
      modeTag: undefined,
    });
    expect(readUnsavedPlanDraft(null)).toEqual({});
  });

  it('只有未使用的草稿可以编辑', () => {
    expect(canEditVersion('draft', false)).toBe(true);
    expect(canEditVersion('draft')).toBe(true);
    expect(canEditVersion('draft', true)).toBe(false);
    expect(canEditVersion('active', false)).toBe(false);
    expect(canEditVersion(undefined, false)).toBe(false);
  });
});

describe('lastNaturalMonth', () => {
  it('取上一个自然月的首尾，平年二月到 28 日', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 2, 15, 8, 0, 0));
    expect(lastNaturalMonth()).toEqual(['2026-02-01', '2026-02-28']);
  });

  it('闰年二月到 29 日', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2024, 2, 15, 8, 0, 0));
    expect(lastNaturalMonth()).toEqual(['2024-02-01', '2024-02-29']);
  });
});

describe('底薪占位符', () => {
  const templates = [
    {
      description: '快捷模板',
      name: '底薪分摊',
      placeholders: [{ label: '底薪金额', token: '{底薪金额}' }],
      skeleton: { 类型: '表达式', 表达式: '{底薪金额} * 方案生效天数 / 周期天数' },
      type: '底薪分摊',
    },
  ];

  it('按模板元数据替换占位符后再写入公式', () => {
    expect(applyBaseSalaryTemplate(2000, templates)).toBe(
      '2000 * 方案生效天数 / 周期天数',
    );
    expect(
      unreplacedPlaceholderLabels(
        { 表达式: applyBaseSalaryTemplate(2000, templates) },
        templates,
      ),
    ).toEqual([]);
  });

  it('花括号和裸词都视为未替换，相邻汉字不算', () => {
    expect(
      unreplacedPlaceholderLabels(
        { 表达式: '{底薪金额} * 方案生效天数 / 周期天数' },
        templates,
      ),
    ).toEqual(['底薪金额']);
    expect(
      unreplacedPlaceholderLabels(
        { 表达式: '底薪金额 × 方案生效天数 / 周期天数' },
        templates,
      ),
    ).toEqual(['底薪金额']);
    expect(unreplacedPlaceholderLabels({ 表达式: '底薪金额额 * 1' }, templates)).toEqual(
      [],
    );
    expect(
      unreplacedPlaceholderLabels(
        { 表达式: '最大值(0, 3000 - 本期已计金额)' },
        templates,
      ),
    ).toEqual([]);
  });
});

describe('方案项 items_hash', () => {
  const basic = [
    {
      condition_json: {},
      enabled: true,
      formula_json: { 类型: '固定金额', 金额: 4 },
      name: '基础单价',
      remark: '忽略',
      sort_order: 10,
      stage: 'per_order',
      subject_id: 1,
    },
  ];

  it('规范化 JSON 与后端 sha256 一致，键序和备注不影响哈希', () => {
    expect(canonicalItemsJson(basic)).toBe(
      '[{"condition_json":{},"enabled":true,"formula_json":{"类型":"固定金额","金额":4},"name":"基础单价","sort_order":10,"stage":"per_order","subject_id":1}]',
    );
    expect(itemsHashOf(basic)).toBe(
      'cc97362f35ea75a50b39edc8ce9e61e7e72eb3a4653872f8dab9174c9314920e',
    );
    expect(itemsHashOf([{ ...basic[0], formula_json: { 金额: 4, 类型: '固定金额' } }])).toBe(
      itemsHashOf(basic),
    );
    expect(emptyPlanItemsHash()).toBe(
      '4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945',
    );
  });

  it('按阶段排序后哈希，金额变化会改变哈希', () => {
    const periodFirst = [
      {
        condition_json: {},
        enabled: true,
        formula_json: { 类型: '固定金额', 金额: 10 },
        name: '周期奖',
        sort_order: 0,
        stage: 'period',
        subject_id: 3,
      },
      {
        condition_json: {},
        enabled: true,
        formula_json: { 类型: '固定金额', 金额: 4 },
        name: '基础单价',
        sort_order: 5,
        stage: 'per_order',
        subject_id: 1,
      },
    ];
    expect(itemsHashOf(periodFirst)).toBe(
      '791b3b70788c43053a0bfd95e0c2fece4cb4a85ea88cb07e130d1e43dfbfe0c3',
    );
    expect(itemsHashOf([{ ...basic[0]!, formula_json: { 类型: '固定金额', 金额: 5 } }])).not.toBe(
      itemsHashOf(basic),
    );
  });

  it('未保存判定只比较 items_hash，已保存且未改动不走未保存试算', () => {
    const saved = draft({
      name: '基础单价',
      remark: '原备注',
      stage: 'per_order',
      formula_json: { 类型: '固定金额', 金额: 4 },
      subject_id: 1,
    });
    const savedHash = planItemsHash([saved]);
    expect(isPlanItemsDirty([saved], savedHash)).toBe(false);
    expect(shouldTrialWithoutSaving(8, isPlanItemsDirty([saved], savedHash))).toBe(false);

    const remarkOnly = { ...saved, remark: '只改备注' };
    expect(isPlanItemsDirty([remarkOnly], savedHash)).toBe(false);
    expect(shouldTrialWithoutSaving(8, isPlanItemsDirty([remarkOnly], savedHash))).toBe(false);

    const edited = {
      ...saved,
      formula_json: { 类型: '固定金额', 金额: 6 },
    };
    expect(isPlanItemsDirty([edited], savedHash)).toBe(true);
    expect(shouldTrialWithoutSaving(8, isPlanItemsDirty([edited], savedHash))).toBe(true);
    expect(shouldTrialWithoutSaving(0, false)).toBe(true);
    expect(UNSAVED_PLAN_LEAVE_MESSAGE).toContain('尚未保存');
  });

  it('没有服务端哈希时，空方案不算脏，有内容算未保存', () => {
    expect(isPlanItemsDirty([], null)).toBe(false);
    expect(isPlanItemsDirty([draft({ name: '基础单价', stage: 'per_order' })], null)).toBe(true);
  });

  it('保存载荷往返后仍等于服务端 items_hash，打开已保存版本不算未保存', () => {
    const drafts = [
      draft({
        name: '基础单价',
        stage: 'per_order',
        formula_json: { 类型: '固定金额', 金额: 4 },
      }),
      draft({ name: '全勤奖', stage: 'period' }),
    ];
    const payload = toSaveItems(drafts);
    const savedHash = itemsHashOf(payload);
    const reloaded = toDraftItems(payload);
    expect(planItemsHash(reloaded)).toBe(savedHash);
    expect(isPlanItemsDirty(reloaded, savedHash)).toBe(false);
    expect(shouldTrialWithoutSaving(12, isPlanItemsDirty(reloaded, savedHash))).toBe(false);
  });
});

describe('阶梯非法组合', () => {
  it('分段累进加固定金额不可选，其余组合可选', () => {
    expect(isIllegalLadderCombo('分段累进', '固定金额')).toBe(true);
    expect(isIllegalLadderCombo('分段累进', '按单价')).toBe(false);
    expect(isIllegalLadderCombo('全量落档', '固定金额')).toBe(false);
    expect(ladderModeDisabled('固定金额', '分段累进')).toBe(true);
    expect(ladderModeDisabled('按单价', '分段累进')).toBe(false);
    expect(ladderModeDisabled('固定金额', '全量落档')).toBe(false);
    expect(ladderPricingDisabled('分段累进', '固定金额')).toBe(true);
    expect(ladderPricingDisabled('分段累进', '按单价')).toBe(false);
    expect(ladderPricingDisabled('全量落档', '固定金额')).toBe(false);
    expect(
      isIllegalLadderFormula({
        类型: '阶梯',
        模式: '分段累进',
        计价: '固定金额',
        字段: '周期单量',
      }),
    ).toBe(true);
    expect(isIllegalLadderFormula({ 类型: '固定金额', 金额: 1 })).toBe(false);
    expect(ILLEGAL_LADDER_MESSAGE).toBe('分段累进模式仅支持按单价计价');
  });
});
