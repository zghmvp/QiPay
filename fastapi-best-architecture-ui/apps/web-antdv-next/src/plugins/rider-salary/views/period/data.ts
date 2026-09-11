import type { PeriodResult } from '../../types/period';

import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeGridProps } from '#/adapter/vxe-table';

import { h } from 'vue';

import { useAccess } from '@vben/access';

import RiderSelect from '../../components/RiderSelect.vue';
import SiteSelect from '../../components/SiteSelect.vue';
import {
  CYCLE_TYPE_OPTIONS,
  enumTagOptions,
  PERIOD_STATUS_OPTIONS,
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
      options: enumTagOptions(PERIOD_STATUS_OPTIONS),
    },
    fieldName: 'status',
    label: '状态',
  },
  {
    component: 'DatePicker',
    componentProps: {
      format: 'YYYY-MM',
      picker: 'month',
      style: { width: '100%' },
      valueFormat: 'YYYY-MM',
    },
    fieldName: 'month',
    label: '年月',
  },
];

function canCalculate(row: PeriodResult) {
  return row.status === 'open' || row.status === 'reopened';
}

function canLock(row: PeriodResult) {
  return row.status === 'open' || row.status === 'reopened';
}

function canMarkPaid(row: PeriodResult) {
  return row.status === 'locked';
}

function canReverse(row: PeriodResult) {
  return row.status === 'locked' || row.status === 'paid';
}

function canDelete(row: PeriodResult) {
  return row.status === 'open' && !(row.payroll_count ?? 0);
}

export function useColumns(
  onActionClick?: OnActionClickFn<PeriodResult>,
): VxeGridProps['columns'] {
  const { hasAccessByCodes } = useAccess();
  return [
    { field: 'seq', title: '序号', type: 'seq', width: 60 },
    { field: 'site_name', minWidth: 120, title: '站点' },
    {
      field: 'rider_name',
      formatter: ({ row }: { row: PeriodResult }) => {
        if (!row.rider_id) return '—';
        return [row.rider_job_no, row.rider_name].filter(Boolean).join(' ') || '—';
      },
      minWidth: 120,
      title: '骑手',
    },
    {
      field: 'start_date',
      formatter: ({ row }: { row: PeriodResult }) =>
        `${row.start_date} ~ ${row.end_date}`,
      minWidth: 200,
      title: '周期区间',
    },
    {
      cellRender: {
        name: 'CellTag',
        options: enumTagOptions(CYCLE_TYPE_OPTIONS),
      },
      field: 'cycle_type',
      title: '类型',
      width: 90,
    },
    {
      cellRender: {
        name: 'CellTag',
        options: enumTagOptions(PERIOD_STATUS_OPTIONS),
      },
      field: 'status',
      title: '状态',
      width: 90,
    },
    { field: 'rider_count', title: '骑手数', width: 80 },
    {
      field: 'stale_count',
      slots: { default: 'stale' },
      title: '需重算',
      width: 90,
    },
    {
      field: 'gross_total',
      slots: { default: 'gross' },
      title: '应发合计',
      width: 120,
    },
    {
      field: 'net_total',
      slots: { default: 'net' },
      title: '实发合计',
      width: 120,
    },
    {
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'site_name',
          nameTitle: '周期',
          onClick: onActionClick,
        },
        name: 'CellOperation',
        options: [
          { code: 'detail', text: '详情' },
          {
            code: 'calculate',
            show: (row: PeriodResult) =>
              hasAccessByCodes(['rs:period:calculate']) && canCalculate(row),
            text: '算薪',
          },
          {
            code: 'lock',
            show: (row: PeriodResult) =>
              hasAccessByCodes(['rs:period:lock']) && canLock(row),
            text: '锁账',
          },
          {
            code: 'mark-paid',
            show: (row: PeriodResult) =>
              hasAccessByCodes(['rs:period:mark-paid']) && canMarkPaid(row),
            text: '标记发薪',
          },
          {
            code: 'reverse',
            show: (row: PeriodResult) =>
              hasAccessByCodes(['rs:period:reverse']) && canReverse(row),
            text: '反冲补发',
          },
          {
            code: 'export',
            show: () => hasAccessByCodes(['rs:period:export']),
            text: '导出',
          },
          {
            code: 'remove',
            show: (row: PeriodResult) =>
              hasAccessByCodes(['rs:period:generate']) && canDelete(row),
            text: '删除',
          },
        ],
      },
      field: 'operation',
      fixed: 'right',
      title: '操作',
      width: 280,
    },
  ];
}
