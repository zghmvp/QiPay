import type {
  EngineEvaluateParam,
  EngineEvaluateResult,
  EngineField,
  EngineFormulaTemplate,
  EngineFunction,
  EngineOperatorsByType,
  EngineOperatorsForField,
  EngineValidateParam,
  EngineValidateResult,
} from '../types/engine';

import { requestClient } from '#/api/request';

const BASE = '/api/v1/rider-salary/engine';

export async function getEngineFieldsApi() {
  return requestClient.get<EngineField[]>(`${BASE}/fields`);
}

export async function getEngineOperatorsApi(field?: string) {
  return requestClient.get<EngineOperatorsByType | EngineOperatorsForField>(
    `${BASE}/operators`,
    { params: field ? { field } : undefined },
  );
}

export async function getEngineFunctionsApi() {
  return requestClient.get<EngineFunction[]>(`${BASE}/functions`);
}

export async function getFormulaTemplatesApi() {
  return requestClient.get<EngineFormulaTemplate[]>(
    `${BASE}/formula-templates`,
  );
}

export async function validateEngineApi(data: EngineValidateParam) {
  return requestClient.post<EngineValidateResult>(`${BASE}/validate`, data);
}

export async function evaluateSampleApi(data: EngineEvaluateParam) {
  return requestClient.post<EngineEvaluateResult>(
    `${BASE}/evaluate-sample`,
    data,
  );
}
