export interface ActivePlanVersion {
  color: string;
  id: number;
  plan_name: string;
  short_name: string;
  version_no: number;
}

export interface PlanBrief {
  code: string;
  color: string;
  id: number;
  name: string;
  short_name: string;
}

export interface PlanDetail {
  code: string;
  color: string;
  created_time: string;
  description?: null | string;
  id: number;
  name: string;
  short_name: string;
  status: string;
  updated_time?: null | string;
}

export interface PlanForm {
  code: string;
  color: string;
  description?: null | string;
  name: string;
  short_name: string;
  status: string;
}

export interface PlanQuery {
  name?: string;
  page?: number;
  size?: number;
  status?: string;
}

export interface PlanItemDetail {
  condition_expr?: null | string;
  condition_json?: null | Record<string, unknown>;
  enabled: boolean;
  formula_expr?: null | string;
  formula_json?: null | Record<string, unknown>;
  id: number;
  name: string;
  plan_version_id: number;
  remark?: null | string;
  sort_order: number;
  stage: string;
  subject_id: number;
  /** 一句话说明（后端派生；备注优先，否则条件+公式摘要） */
  summary?: null | string;
}

export interface PlanItemParam {
  condition_json?: null | Record<string, unknown>;
  enabled: boolean;
  formula_json?: null | Record<string, unknown>;
  name: string;
  remark?: null | string;
  sort_order: number;
  stage: string;
  subject_id: number;
}

export interface PlanItemDraft extends PlanItemParam {
  _key: string;
  condition_expr?: null | string;
  formula_expr?: null | string;
  id?: number;
  subject_id: number;
}

export interface PlanVersionDetail {
  activated_time?: null | string;
  copied_from_id?: null | number;
  created_time: string;
  disabled_time?: null | string;
  id: number;
  is_used: boolean;
  items: PlanItemDetail[];
  items_hash?: null | string;
  mode_tag: string;
  plan?: null | PlanBrief;
  plan_id: number;
  remark?: null | string;
  status: string;
  binding_trial_passed?: boolean | null;
  trial_hash?: null | string;
  trial_mode?: null | string;
  trial_passed: boolean;
  trial_snapshot?: null | Record<string, unknown>;
  updated_time?: null | string;
  version_no: number;
  voided_time?: null | string;
}

export interface PlanVersionQuery {
  page?: number;
  plan_id?: number;
  size?: number;
  status?: string;
}

export interface CreatePlanVersionParam {
  mode_tag?: string;
  plan_id: number;
  remark?: null | string;
}

export interface UpdatePlanVersionParam {
  mode_tag?: string;
  remark?: null | string;
}

export interface TrialParam {
  end_date: string;
  /** full_version | binding_segments */
  mode?: 'binding_segments' | 'full_version';
  rider_id: number;
  start_date: string;
}

export interface TrialSegmentOrderCount {
  end_date: string;
  plan_order_count: number;
  plan_version_id: number;
  start_date: string;
}

export interface TrialSummary {
  advance_deductible?: number | string;
  advance_deduction?: number | string;
  bonus_total?: null | number | string;
  deduction_total: number | string;
  gross: number | string;
  manual_bonus: number | string;
  manual_penalty: number | string;
  net: number | string;
  order_count: number;
  penalty_total?: null | number | string;
  period_total: number | string;
  per_order_total: number | string;
  daily_total: number | string;
  /** 方案期内单量（各段合计；强制全程生效试算通常等于周期有效单量） */
  plan_order_count?: number;
  plan_period_order_count?: number;
  /** 周期有效单量（后端 Cycle 13 别名） */
  period_valid_order_count?: number;
  segment_order_counts?: TrialSegmentOrderCount[];
  /** 周期有效单量 */
  valid_order_count?: number;
  warnings?: string[];
}

export interface TrialCalcItem {
  amount: number | string;
  calc_trace?: Record<string, unknown>;
  name: string;
  plan_version_id?: null | number;
}

export interface TrialPerOrderRow {
  biz_date?: null | string;
  items: TrialCalcItem[];
  order_id?: null | number;
  order_no?: null | string;
}

export interface TrialDailyRow {
  amount: number | string;
  biz_date: string;
  day_status?: null | string;
  items?: TrialCalcItem[];
  order_count: number;
}

export interface TrialResult {
  adjustments?: Record<string, unknown>[];
  daily: TrialDailyRow[];
  matches_official_calculate?: boolean;
  mode?: string;
  mode_label?: string;
  passed: boolean;
  period_items: TrialCalcItem[];
  per_order: TrialPerOrderRow[];
  summary: TrialSummary;
  trial_hash?: null | string;
  warnings?: string[];
}

export interface RollbackPreviewRider {
  end_date?: null | string;
  job_no?: null | string;
  name?: null | string;
  rider_id: number;
  start_date?: null | string;
}

export interface RollbackPreviewPayroll {
  id: number;
  kind: string;
  period_id: number;
  rider_id: number;
  status: string;
}

export interface RollbackPreviewResult {
  binding_count: number;
  consequences: string[];
  has_paid: boolean;
  payrolls: RollbackPreviewPayroll[];
  payrolls_draft: number;
  payrolls_finalized: number;
  payrolls_paid: number;
  periods_reopened: number;
  reversal_count: number;
  riders: RollbackPreviewRider[];
  version_id: number;
  version_label: string;
}

export interface RollbackParam {
  confirm_text: string;
  reason: string;
}

export interface ConditionLeaf {
  值?: unknown;
  字段?: string;
  运算符?: string;
}

export interface ConditionGroup {
  条件: Array<ConditionGroup | ConditionLeaf>;
  逻辑: '且' | '或' | '非';
}

export type FormulaKind = '固定金额' | '字段乘单价' | '表达式' | '阶梯';

export interface LadderTier {
  上限?: null | number;
  下限: number;
  值: number;
}
