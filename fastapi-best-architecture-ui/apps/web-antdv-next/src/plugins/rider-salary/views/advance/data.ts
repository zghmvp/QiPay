import type { AdvanceResult } from '../../types/advance';

import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeGridProps } from '#/adapter/vxe-table';

import { h } from 'vue';

import { useAccess } from '@vben/access';

import RiderSelect from '../../components/RiderSelect.vue';
import SiteSelect from '../../components/SiteSelect.vue';
import {
  ADVANCE_STATUS_OPTIONS,
  DEDUCT_STATUS_OPTIONS,
  enumTagOptions,
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
    component: 'Select',
    componentProps: {
      allowClear: true,
      options: enumTagOptions(ADVANCE_STATUS_OPTIONS),
    },
    fieldName: 'status',
    label: '状态',
  },
  {
    component: 'RangePicker',
    fieldName: 'date_range',
    label: '申请日期',
  },
];

export function useColumns(
  onActionClick?: OnActionClickFn<AdvanceResult>,
): VxeGridProps['columns'] {
  const { hasAccessByCodes } = useAccess();
  return [
    { field: 'seq', title: '序号', type: 'seq', width: 60 },
    {
      field: 'rider_name',
      formatter: ({ row }: { row: AdvanceResult }) =>
        [row.rider_job_no, row.rider_name].filter(Boolean).join(' ') || '—',
      minWidth: 140,
      title: '骑手',
    },
    { field: 'site_name', minWidth: 120, title: '站点' },
    {
      field: 'amount',
      slots: { default: 'amount' },
      title: '金额',
      width: 110,
    },
    { field: 'reason', minWidth: 160, title: '原因' },
    {
      cellRender: {
        name: 'CellTag',
        options: enumTagOptions(ADVANCE_STATUS_OPTIONS),
      },
      field: 'status',
      title: '状态',
      width: 100,
    },
    { field: 'submit_time', minWidth: 170, title: '申请时间' },
    { field: 'approver_name', title: '审核人', width: 100 },
    { field: 'paid_time', minWidth: 170, title: '发放时间' },
    {
      field: 'deducted_amount',
      slots: { default: 'deducted' },
      title: '已抵扣',
      width: 110,
    },
    {
      field: 'remaining_amount',
      slots: { default: 'remaining' },
      title: '待抵扣',
      width: 110,
    },
    {
      cellRender: {
        name: 'CellTag',
        options: enumTagOptions(DEDUCT_STATUS_OPTIONS),
      },
      field: 'deduct_status',
      title: '抵扣',
      width: 100,
    },
    {
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'rider_name',
          nameTitle: '预支',
          onClick: onActionClick,
        },
        name: 'CellOperation',
        options: [
          { code: 'detail', text: '详情' },
          {
            code: 'approve',
            show: (row: AdvanceResult) =>
              hasAccessByCodes(['rs:advance:approve']) && row.status === 'pending',
            text: '通过',
          },
          {
            code: 'reject',
            show: (row: AdvanceResult) =>
              hasAccessByCodes(['rs:advance:reject']) && row.status === 'pending',
            text: '驳回',
          },
          {
            code: 'mark-paid',
            show: (row: AdvanceResult) =>
              hasAccessByCodes(['rs:advance:mark-paid']) &&
              row.status === 'to_pay',
            text: '标记已发放',
          },
          {
            code: 'cancel',
            show: (row: AdvanceResult) =>
              hasAccessByCodes(['rs:advance:cancel']) && row.status === 'to_pay',
            text: '取消',
          },
        ],
      },
      field: 'operation',
      fixed: 'right',
      title: '操作',
      width: 220,
    },
  ];
}
