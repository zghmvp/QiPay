from typing import Annotated, Any

from fastapi import APIRouter, Query

from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.plugin.rider_salary.schema.engine import (
    EngineEvaluateParam,
    EngineEvaluateResult,
    EngineValidateParam,
    EngineValidateResult,
)
from backend.plugin.rider_salary.service.engine_service import engine_service

router = APIRouter()


@router.get('/fields', summary='字段注册表', description='按阶段可用的公式字段', dependencies=[DependsJwtAuth])
async def get_engine_fields() -> ResponseSchemaModel[list[dict[str, Any]]]:
    return response_base.success(data=engine_service.list_fields())


@router.get('/operators', summary='运算符', description='按字段类型返回可用运算符', dependencies=[DependsJwtAuth])
async def get_engine_operators(
    field: Annotated[str | None, Query(description='字段中文名')] = None,
) -> ResponseSchemaModel[dict[str, Any]]:
    return response_base.success(data=engine_service.list_operators(field))


@router.get('/functions', summary='函数', description='白名单函数签名与说明', dependencies=[DependsJwtAuth])
async def get_engine_functions() -> ResponseSchemaModel[list[dict[str, Any]]]:
    return response_base.success(data=engine_service.list_functions())


@router.get(
    '/formula-templates',
    summary='公式模板',
    description='四种公式模板骨架与底薪分摊快捷模板',
    dependencies=[DependsJwtAuth],
)
async def get_formula_templates() -> ResponseSchemaModel[list[dict[str, Any]]]:
    return response_base.success(data=engine_service.list_templates())


@router.post('/validate', summary='校验条件与公式', dependencies=[DependsJwtAuth])
async def validate_formula(obj: EngineValidateParam) -> ResponseSchemaModel[EngineValidateResult]:
    return response_base.success(data=engine_service.validate(obj))


@router.post('/evaluate-sample', summary='即时预览求值', dependencies=[DependsJwtAuth])
async def evaluate_sample(obj: EngineEvaluateParam) -> ResponseSchemaModel[EngineEvaluateResult]:
    return response_base.success(data=engine_service.evaluate_sample(obj))
