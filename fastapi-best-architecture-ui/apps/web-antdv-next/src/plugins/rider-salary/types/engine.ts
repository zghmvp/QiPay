export interface EngineField {
  description: string;
  enum_options?: Array<{ label: string; value: number | string }>;
  name: string;
  stages: string[];
  type: string;
  unit?: null | string;
}

export interface EngineFunction {
  description: string;
  name: string;
  signature: string;
}

export interface EngineFormulaTemplate {
  compiled_example?: string;
  description: string;
  name: string;
  skeleton: Record<string, unknown>;
  type: string;
}

export interface EngineValidateParam {
  condition_json?: null | Record<string, unknown>;
  formula_json?: null | Record<string, unknown>;
  stage: string;
}

export interface EngineValidateResult {
  condition_expr: string;
  errors: string[];
  formula_expr: string;
  ok: boolean;
}

export interface EngineEvaluateParam extends EngineValidateParam {
  context?: Record<string, unknown>;
}

export interface EngineEvaluateResult {
  amount: number;
  hit: boolean;
  trace: Record<string, unknown>;
}

export type EngineOperatorsByType = Record<string, string[]>;

export interface EngineOperatorsForField {
  field: string;
  operators: string[];
  type: null | string;
}
