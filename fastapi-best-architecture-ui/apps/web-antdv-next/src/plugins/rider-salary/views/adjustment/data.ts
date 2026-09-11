import type { AdjustmentResult } from '../../types/adjustment';

import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeGridProps } from '#/adapter/vxe-table';

import { h } from 'vue';

import { useAccess } from '@vben/access';

import RiderSelect from '../../components/RiderSelect.vue';
import SiteSelect from '../../components/SiteSelect.vue';
import SubjectSelect from '../../components/SubjectSelect.vue';
import {
  enumTagOptions,
  SUBJECT_DIRECTION_OPTIONS,
} from '../../constants/enums';

export const querySchema: VbenFormSchema[] = [
  {
    component: h(SiteSelect),
    fieldName: 'site_id',
    label: '站点',
    modelPropName: 'value',
  },
  {
    component: h(RiderSelect),
    dependencies: {
      componentProps: (values) => ({ siteId: values.site_id }),
      triggerFields: ['site_id'],
    },
    fieldName: 'rider_id',
    label: '骑手',
    modelPropName: 'value',
  },
  {
    component: 'RangePicker',
    fieldName: 'date_range',
    label: '日期范围',
  },
  {
    component: h(SubjectSelect),
    fieldName: 'subject_id',
    label: '科目',
    modelPropName: 'value',
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
];

export const adjustmentFormSchema: VbenFormSchema[] = [
  {
    component: h(SiteSelect),
    fieldName: 'site_id',
    label: '站点',
    modelPropName: 'value',
    rules: 'selectRequired',
  },
  {
    component: h(RiderSelect),
    dependencies: {
      componentProps: (values) => ({ siteId: values.site_id }),
      triggerFields: ['site_id'],
    },
    fieldName: 'rider_id',
    label: '骑手',
    modelPropName: 'value',
    rules: 'selectRequired',
  },
  {
    component: 'DatePicker',
    componentProps: {
      format: 'YYYY-MM-DD',
      style: { width: '100%' },
      valueFormat: 'YYYY-MM-DD',
    },
    fieldName: 'biz_date',
    label: '业务日期',
    rules: 'required',
  },
  {
    component: h(SubjectSelect),
    fieldName: 'subject_id',
    label: '科目',
    modelPropName: 'value',
    rules: 'selectRequired',
  },
  {
    component: 'InputNumber',
    componentProps: {
      precision: 2,
      style: { width: '100%' },
    },
    fieldName: 'amount',
    label: '金额',
    rules: 'required',
  },
  {
    component: 'Textarea',
    fieldName: 'remark',
    label: '备注',
    rules: 'required',
  },
];

export function useColumns(
  onActionClick?: OnActionClickFn<AdjustmentResult>,
): VxeGridProps['columns'] {
  const { hasAccessByCodes } = useAccess();
  return [
    { field: 'seq', title: '序号', type: 'seq', width: 60 },
    {
      field: 'is_locked',
      slots: { default: 'locked' },
      title: '锁账',
      width: 70,
    },
    { field: 'biz_date', title: '日期', width: 120 },
    { field: 'rider_job_no', title: '工号', width: 100 },
    { field: 'rider_name', title: '骑手', width: 100 },
    { field: 'subject_name', minWidth: 120, title: '科目' },
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
      field: 'signed_amount',
      slots: { default: 'amount' },
      title: '金额',
      width: 110,
    },
    { field: 'remark', minWidth: 140, title: '备注' },
    {
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'rider_name',
          nameTitle: '奖惩',
          onClick: onActionClick,
        },
        name: 'CellOperation',
        options: [
          {
            code: 'edit',
            show: (row: AdjustmentResult) =>
              hasAccessByCodes(['rs:adjustment:edit']) && !row.is_locked,
            text: '编辑',
          },
          {
            code: 'delete',
            show: (row: AdjustmentResult) =>
              hasAccessByCodes(['rs:adjustment:del']) && !row.is_locked,
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
