import type { PayrollSummary } from '../../types/payroll';

import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeGridProps } from '#/adapter/vxe-table';

import { h } from 'vue';

import { useAccess } from '@vben/access';

import RiderSelect from '../../components/RiderSelect.vue';
import SiteSelect from '../../components/SiteSelect.vue';
import {
  enumTagOptions,
  PAYROLL_KIND_OPTIONS,
  PAYROLL_STATUS_OPTIONS,
} from '../../constants/enums';

export const querySchema: VbenFormSchema[] = [
  {
    component: h(SiteSelect),
    fieldName: 'site_id',
    label: '站点',
    modelPropName: 'value',
  },
  {
    component: 'InputNumber',
    componentProps: { class: 'w-full', min: 1, placeholder: '周期 ID' },
    fieldName: 'period_id',
    label: '周期',
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
      options: enumTagOptions(PAYROLL_STATUS_OPTIONS),
    },
    fieldName: 'status',
    label: '状态',
  },
  {
    component: 'Select',
    componentProps: {
      allowClear: true,
      options: [
        { label: '是', value: true },
        { label: '否', value: false },
      ],
    },
    fieldName: 'stale',
    label: '需重算',
  },
  {
    component: 'Select',
    componentProps: {
      allowClear: true,
      options: enumTagOptions(PAYROLL_KIND_OPTIONS),
    },
    fieldName: 'kind',
    label: '单据类型',
  },
];

export function useColumns(
  onActionClick?: OnActionClickFn<PayrollSummary>,
): VxeGridProps['columns'] {
  const { hasAccessByCodes } = useAccess();
  return [
    { field: 'seq', title: '序号', type: 'seq', width: 60 },
    {
      field: 'job_no',
      formatter: ({ row }: { row: PayrollSummary }) =>
        [row.rider_job_no || row.job_no, row.rider_name]
          .filter(Boolean)
          .join(' ') || '—',
      minWidth: 140,
      title: '骑手',
    },
    { field: 'site_name', minWidth: 120, title: '站点' },
    {
      field: 'period_range',
      formatter: ({ row }: { row: PayrollSummary }) =>
        row.period_start && row.period_end
          ? `${row.period_start} ~ ${row.period_end}`
          : '—',
      minWidth: 200,
      title: '周期区间',
    },
    {
      cellRender: {
        name: 'CellTag',
        options: enumTagOptions(PAYROLL_KIND_OPTIONS),
      },
      field: 'kind',
      title: '类型',
      width: 90,
    },
    {
      cellRender: {
        name: 'CellTag',
        options: enumTagOptions(PAYROLL_STATUS_OPTIONS),
      },
      field: 'status',
      title: '状态',
      width: 90,
    },
    { field: 'order_count', title: '单量', width: 70 },
    {
      field: 'gross',
      slots: { default: 'gross' },
      title: '应发',
      width: 110,
    },
    {
      field: 'net',
      slots: { default: 'net' },
      title: '实发',
      width: 110,
    },
    {
      field: 'stale',
      formatter: ({ cellValue }: { cellValue: boolean }) =>
        cellValue ? '是' : '否',
      title: '需重算',
      width: 80,
    },
    {
      field: 'calc_time',
      formatter: 'formatDateTime',
      minWidth: 170,
      title: '计算时间',
    },
    {
      align: 'center',
      cellRender: {
        attrs: {
          name: 'payroll-action',
          onClick: onActionClick,
        },
        name: 'CellOperation',
        options: [
          {
            code: 'detail',
            show: () => hasAccessByCodes(['rs:payroll:view']),
            text: '明细',
          },
        ],
      },
      field: 'operation',
      fixed: 'right',
      title: '操作',
      width: 100,
    },
  ];
}
