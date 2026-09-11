import type { AuditLogResult } from '../../types/audit';

import type { VbenFormSchema } from '#/adapter/form';
import type { VxeGridProps } from '#/adapter/vxe-table';

import { AUDIT_MODULE_OPTIONS, enumTagOptions } from '../../constants/enums';

export const querySchema: VbenFormSchema[] = [
  {
    component: 'Select',
    componentProps: {
      allowClear: true,
      options: enumTagOptions(AUDIT_MODULE_OPTIONS),
      showSearch: true,
    },
    fieldName: 'module',
    label: '模块',
  },
  {
    component: 'Input',
    fieldName: 'action',
    label: '动作',
  },
  {
    component: 'Input',
    fieldName: 'operator',
    label: '操作人',
  },
  {
    component: 'RangePicker',
    componentProps: {
      showTime: true,
      valueFormat: 'YYYY-MM-DD HH:mm:ss',
    },
    fieldName: 'date_range',
    label: '日期范围',
  },
  {
    component: 'Input',
    fieldName: 'keyword',
    label: '关键字',
  },
];

export function useColumns(): VxeGridProps['columns'] {
  return [
    { type: 'expand', width: 50, slots: { content: 'expandContent' } },
    { field: 'seq', title: '序号', type: 'seq', width: 60 },
    { field: 'operate_time', title: '时间', width: 170 },
    { field: 'module', title: '模块', width: 110 },
    { field: 'action', title: '动作', width: 120 },
    { field: 'operator_name', title: '操作人', width: 110 },
    { field: 'target_label', minWidth: 140, title: '对象' },
    { field: 'description', align: 'left', minWidth: 280, title: '描述' },
  ];
}

export type { AuditLogResult };
