import type { SiteResult } from '../../types/site';

import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeGridProps } from '#/adapter/vxe-table';

import { useAccess } from '@vben/access';

import {
  CYCLE_TYPE_OPTIONS,
  ENABLE_STATUS_OPTIONS,
  enumTagOptions,
} from '../../constants/enums';
import { formatCycleSummary } from '../../utils/date';
import { formatMonthlyAdvanceLimit } from './helpers';

export const querySchema: VbenFormSchema[] = [
  {
    component: 'Input',
    fieldName: 'code',
    label: '站点编码',
  },
  {
    component: 'Input',
    fieldName: 'name',
    label: '站点名称',
  },
  {
    component: 'Select',
    componentProps: {
      allowClear: true,
      options: enumTagOptions(ENABLE_STATUS_OPTIONS),
      placeholder: '请选择状态',
    },
    fieldName: 'status',
    label: '状态',
  },
];

export const siteFormSchema: VbenFormSchema[] = [
  {
    component: 'Input',
    fieldName: 'code',
    label: '站点编码',
    rules: 'required',
  },
  {
    component: 'Input',
    fieldName: 'name',
    label: '站点名称',
    rules: 'required',
  },
  {
    component: 'Select',
    componentProps: {
      options: enumTagOptions(CYCLE_TYPE_OPTIONS),
    },
    defaultValue: 'month',
    fieldName: 'settle_cycle',
    label: '结算周期',
    rules: 'selectRequired',
  },
  {
    component: 'InputNumber',
    componentProps: {
      max: 31,
      min: 1,
      placeholder: '每月起始日 1–31',
      style: { width: '100%' },
    },
    dependencies: {
      required: (values) => values.settle_cycle === 'custom',
      show: (values) => values.settle_cycle === 'custom',
      triggerFields: ['settle_cycle'],
    },
    fieldName: 'anchor_day',
    label: '周期起始日',
  },
  {
    component: 'InputNumber',
    componentProps: {
      min: 0,
      precision: 2,
      style: { width: '100%' },
    },
    fieldName: 'advance_limit',
    help: '单笔预支金额上限（元）。空则用全局金额默认。与每月次数无关。',
    label: '预支金额上限',
    renderComponentContent: () => ({
      addonAfter: () => '元',
    }),
  },
  {
    component: 'InputNumber',
    componentProps: {
      min: 0,
      placeholder: '空则按 1 保存',
      precision: 0,
      step: 1,
      style: { width: '100%' },
    },
    defaultValue: 1,
    fieldName: 'monthly_advance_limit',
    help: '每个骑手每个自然月可申请次数。空则按 1 保存。0 表示本站禁止预支。与金额上限无关。',
    label: '每月可预支次数',
    renderComponentContent: () => ({
      addonAfter: () => '次',
    }),
  },
  {
    component: 'RadioGroup',
    componentProps: {
      buttonStyle: 'solid',
      optionType: 'button',
      options: enumTagOptions(ENABLE_STATUS_OPTIONS),
    },
    defaultValue: 'enable',
    fieldName: 'status',
    label: '状态',
    rules: 'selectRequired',
  },
  {
    component: 'Textarea',
    fieldName: 'remark',
    label: '备注',
  },
];

export function useColumns(
  onActionClick?: OnActionClickFn<SiteResult>,
): VxeGridProps['columns'] {
  const { hasAccessByCodes } = useAccess();
  return [
    { field: 'seq', title: '序号', type: 'seq', width: 60 },
    { field: 'code', minWidth: 100, title: '编码' },
    { field: 'name', minWidth: 140, title: '名称' },
    {
      cellRender: {
        name: 'CellTag',
        options: enumTagOptions(CYCLE_TYPE_OPTIONS),
      },
      field: 'settle_cycle',
      title: '周期类型',
      width: 110,
    },
    {
      field: 'cycle_summary',
      formatter: ({ row }: { row: SiteResult }) =>
        formatCycleSummary(row.settle_cycle, row.cycle_config),
      minWidth: 140,
      title: '周期配置',
    },
    {
      field: 'advance_limit',
      slots: { default: 'advance_limit' },
      title: '预支金额上限',
      width: 130,
    },
    {
      field: 'monthly_advance_limit',
      formatter: ({ row }: { row: SiteResult }) =>
        formatMonthlyAdvanceLimit(row.monthly_advance_limit),
      title: '每月可预支次数',
      width: 150,
    },
    {
      cellRender: {
        name: 'CellTag',
        options: enumTagOptions(ENABLE_STATUS_OPTIONS),
      },
      field: 'status',
      title: '状态',
      width: 90,
    },
    {
      field: 'manager_count',
      slots: { default: 'manager_count' },
      title: '负责人数',
      width: 100,
    },
    {
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'name',
          nameTitle: '站点',
          onClick: onActionClick,
        },
        name: 'CellOperation',
        options: [
          {
            code: 'edit',
            show: () => hasAccessByCodes(['rs:site:edit']),
            text: '编辑',
          },
          {
            code: 'managers',
            show: () => hasAccessByCodes(['rs:site:manager']),
            text: '负责人',
          },
          {
            code: 'delete',
            show: () => hasAccessByCodes(['rs:site:del']),
            text: '删除',
          },
        ],
      },
      field: 'operation',
      fixed: 'right',
      title: '操作',
      width: 200,
    },
  ];
}
