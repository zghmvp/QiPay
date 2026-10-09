import type { PlanItemDraft } from '../types/plan';
import type { SubjectResult } from '../types/subject';

import rawCatalog from './plan-presets.json';

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

export const PLAN_PRESET_CATEGORIES = rawCatalog.categories;

export const PLAN_PRESETS = rawCatalog.presets as PlanPreset[];

export function resolveSubjectId(code: string, subjects: SubjectResult[]): number {
  return subjects.find((item) => item.code === code)?.id ?? 0;
}

export function buildItemsFromPreset(preset: PlanPreset, subjects: SubjectResult[]): PlanItemDraft[] {
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
