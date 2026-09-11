import type { SubjectResult } from '../../types/subject';

import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeGridProps } from '#/adapter/vxe-table';

import { useAccess } from '@vben/access';

import {
  ENABLE_STATUS_OPTIONS,
  ENTRY_GRANULARITY_OPTIONS,
  enumTagOptions,
  FEE_MODE_OPTIONS,
  SUBJECT_DIRECTION_OPTIONS,
} from '../../constants/enums';

export const querySchema: VbenFormSchema[] = [
  {
    component: 'Input',
    fieldName: 'name',
    label: '科目名称',
  },
  {
    component: 'Select',
    componentProps: {
      allowClear: true,
      options: enumTagOptions(SUBJECT_DIRECTION_OPTIONS),
    },
    fieldName: 'direction',
    label: '方向',
  },
  {
    component: 'Select',
    componentProps: {
      allowClear: true,
      options: enumTagOptions(ENABLE_STATUS_OPTIONS),
    },
    fieldName: 'status',
    label: '状态',
  },
];

export const subjectFormSchema: VbenFormSchema[] = [
  {
    component: 'Input',
    dependencies: {
      disabled: (values) => Boolean(values.is_builtin),
      triggerFields: ['is_builtin'],
    },
    fieldName: 'code',
    label: '科目编码',
    rules: 'required',
  },
  {
    component: 'Input',
    fieldName: 'name',
    label: '科目名称',
    rules: 'required',
  },
  {
    component: 'RadioGroup',
    componentProps: {
      buttonStyle: 'solid',
      optionType: 'button',
      options: enumTagOptions(SUBJECT_DIRECTION_OPTIONS),
    },
    dependencies: {
      disabled: (values) => Boolean(values.is_builtin),
      triggerFields: ['is_builtin'],
    },
    fieldName: 'direction',
    label: '方向',
    rules: 'selectRequired',
  },
  {
    component: 'Select',
    componentProps: {
      options: enumTagOptions(FEE_MODE_OPTIONS),
    },
    defaultValue: 'formula',
    fieldName: 'fee_mode',
    label: '计费方式',
    rules: 'selectRequired',
  },
  {
    component: 'InputNumber',
    componentProps: {
      precision: 2,
      style: { width: '100%' },
    },
    dependencies: {
      show: (values) => values.fee_mode === 'fixed',
      triggerFields: ['fee_mode'],
    },
    fieldName: 'fixed_amount',
    label: '定额金额',
  },
  {
    component: 'Switch',
    dependencies: {
      disabled: (values) => Boolean(values.is_builtin),
      triggerFields: ['is_builtin'],
    },
    defaultValue: true,
    fieldName: 'include_in_gross',
    label: '计入应发',
  },
  {
    component: 'Select',
    componentProps: {
      options: enumTagOptions(ENTRY_GRANULARITY_OPTIONS),
    },
    defaultValue: 'both',
    fieldName: 'entry_granularity',
    label: '入账粒度',
    rules: 'selectRequired',
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
    component: 'InputNumber',
    componentProps: {
      min: 0,
      style: { width: '100%' },
    },
    defaultValue: 0,
    fieldName: 'sort_order',
    label: '排序',
  },
  {
    component: 'Textarea',
    fieldName: 'remark',
    label: '备注',
  },
  {
    component: 'Input',
    dependencies: {
      show: () => false,
      triggerFields: ['is_builtin'],
    },
    fieldName: 'is_builtin',
    label: '内置',
  },
];

export function useColumns(
  onActionClick?: OnActionClickFn<SubjectResult>,
): VxeGridProps['columns'] {
  const { hasAccessByCodes } = useAccess();
  return [
    { field: 'seq', title: '序号', type: 'seq', width: 60 },
    { field: 'code', minWidth: 120, title: '编码' },
    { field: 'name', minWidth: 120, title: '名称' },
    {
      cellRender: {
        name: 'CellTag',
        options: enumTagOptions(SUBJECT_DIRECTION_OPTIONS),
      },
      field: 'direction',
      title: '方向',
      width: 80,
    },
    {
      cellRender: {
        name: 'CellTag',
        options: enumTagOptions(FEE_MODE_OPTIONS),
      },
      field: 'fee_mode',
      title: '计费方式',
      width: 110,
    },
    {
      field: 'fixed_amount',
      slots: { default: 'fixed_amount' },
      title: '定额',
      width: 100,
    },
    {
      field: 'include_in_gross',
      formatter: ({ cellValue }: { cellValue: boolean }) =>
        cellValue ? '是' : '否',
      title: '进应发',
      width: 80,
    },
    {
      cellRender: {
        name: 'CellTag',
        options: enumTagOptions(ENTRY_GRANULARITY_OPTIONS),
      },
      field: 'entry_granularity',
      title: '入账粒度',
      width: 120,
    },
    {
      field: 'is_builtin',
      formatter: ({ cellValue }: { cellValue: boolean }) =>
        cellValue ? '内置' : '自定义',
      title: '内置',
      width: 80,
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
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'name',
          nameTitle: '科目',
          onClick: onActionClick,
        },
        name: 'CellOperation',
        options: [
          {
            code: 'edit',
            show: () => hasAccessByCodes(['rs:subject:edit']),
            text: '编辑',
          },
          {
            code: 'delete',
            show: (row: SubjectResult) =>
              hasAccessByCodes(['rs:subject:del']) && !row.is_builtin,
            text: '删除',
          },
        ],
      },
      field: 'operation',
      fixed: 'right',
      title: '操作',
      width: 140,
    },
  ];
}
