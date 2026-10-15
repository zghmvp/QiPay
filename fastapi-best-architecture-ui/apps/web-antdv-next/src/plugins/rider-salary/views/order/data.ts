import type { OrderResult } from '../../types/order';

import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeGridProps } from '#/adapter/vxe-table';

import { h } from 'vue';

import { useAccess } from '@vben/access';

import dayjs from 'dayjs';

import RiderSelect from '../../components/RiderSelect.vue';
import SiteSelect from '../../components/SiteSelect.vue';
import {
  enumTagOptions,
  ORDER_SOURCE_OPTIONS,
  ORDER_STATUS_OPTIONS,
} from '../../constants/enums';

const dateRangePresets = [
  { label: '今天', value: () => [dayjs(), dayjs()] },
  {
    label: '昨天',
    value: () => [dayjs().subtract(1, 'day'), dayjs().subtract(1, 'day')],
  },
  { label: '近7天', value: () => [dayjs().subtract(6, 'day'), dayjs()] },
  {
    label: '本月',
    value: () => [dayjs().startOf('month'), dayjs().endOf('month')],
  },
  {
    label: '上月',
    value: () => [
      dayjs().subtract(1, 'month').startOf('month'),
      dayjs().subtract(1, 'month').endOf('month'),
    ],
  },
];

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
    componentProps: {
      allowClear: true,
      format: 'YYYY-MM-DD',
      placeholder: ['开始日期', '结束日期'],
      presets: dateRangePresets,
      style: { width: '100%' },
      valueFormat: 'YYYY-MM-DD',
    },
    fieldName: 'date_range',
    formItemClass: 'md:col-span-2',
    label: '业务日期',
  },
  {
    component: 'Select',
    componentProps: {
      allowClear: true,
      options: enumTagOptions(ORDER_STATUS_OPTIONS),
      placeholder: '全部状态',
    },
    fieldName: 'status',
    label: '状态',
  },
  {
    component: 'Select',
    componentProps: {
      allowClear: true,
      options: enumTagOptions(ORDER_SOURCE_OPTIONS),
      placeholder: '全部来源',
    },
    fieldName: 'source',
    label: '来源',
  },
  {
    component: 'Input',
    componentProps: {
      allowClear: true,
      placeholder: '订单号',
    },
    fieldName: 'order_no',
    label: '订单号',
  },
  {
    component: 'InputNumber',
    componentProps: {
      min: 1,
      style: { width: '100%' },
    },
    fieldName: 'import_batch_id',
    label: '批次',
  },
  {
    component: 'Select',
    componentProps: {
      allowClear: true,
      options: [
        { label: '已锁账', value: true },
        { label: '未锁账', value: false },
      ],
    },
    fieldName: 'is_locked',
    label: '是否锁账',
  },
  {
    component: 'InputNumber',
    componentProps: {
      min: 0,
      placeholder: '最小',
      style: { width: '100%' },
    },
    fieldName: 'distance_min',
    label: '距离起（公里）',
  },
  {
    component: 'InputNumber',
    componentProps: {
      min: 0,
      placeholder: '最大',
      style: { width: '100%' },
    },
    fieldName: 'distance_max',
    label: '距离止（公里）',
  },
  {
    component: 'InputNumber',
    componentProps: {
      min: 0,
      placeholder: '最小',
      style: { width: '100%' },
    },
    fieldName: 'weight_min',
    label: '重量起（斤）',
  },
  {
    component: 'InputNumber',
    componentProps: {
      min: 0,
      placeholder: '最大',
      style: { width: '100%' },
    },
    fieldName: 'weight_max',
    label: '重量止（斤）',
  },
];

export const orderFormSchema: VbenFormSchema[] = [
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
    component: 'Input',
    fieldName: 'order_no',
    label: '订单号',
    rules: 'required',
  },
  {
    component: 'InputNumber',
    componentProps: {
      min: 0,
      precision: 2,
      style: { width: '100%' },
    },
    fieldName: 'distance_km',
    label: '配送距离（公里）',
    rules: 'required',
  },
  {
    component: 'InputNumber',
    componentProps: {
      min: 0,
      precision: 2,
      style: { width: '100%' },
    },
    fieldName: 'weight_jin',
    label: '商品重量（斤）',
    rules: 'required',
  },
  {
    component: 'DatePicker',
    componentProps: {
      format: 'YYYY-MM-DD HH:mm:ss',
      showTime: true,
      style: { width: '100%' },
      valueFormat: 'YYYY-MM-DD HH:mm:ss',
    },
    fieldName: 'order_time',
    label: '下单时间',
    rules: 'required',
  },
  {
    component: 'DatePicker',
    componentProps: {
      format: 'YYYY-MM-DD HH:mm:ss',
      showTime: true,
      style: { width: '100%' },
      valueFormat: 'YYYY-MM-DD HH:mm:ss',
    },
    fieldName: 'deliver_time',
    label: '送达时间',
  },
  {
    component: 'Select',
    componentProps: {
      options: enumTagOptions(ORDER_STATUS_OPTIONS),
    },
    defaultValue: 'completed',
    fieldName: 'status',
    label: '订单状态',
    rules: 'selectRequired',
  },
  {
    component: 'InputNumber',
    componentProps: {
      min: 0,
      precision: 2,
      style: { width: '100%' },
    },
    fieldName: 'amount',
    label: '订单金额',
  },
  {
    component: 'Textarea',
    fieldName: 'remark',
    label: '备注',
  },
];

export function useColumns(
  onActionClick?: OnActionClickFn<OrderResult>,
): VxeGridProps['columns'] {
  const { hasAccessByCodes } = useAccess();
  return [
    { field: 'seq', title: '序号', type: 'seq', width: 60 },
    { field: 'order_no', minWidth: 140, title: '订单号' },
    {
      field: 'rider_name',
      formatter: ({ row }: { row: OrderResult }) =>
        [row.rider_job_no, row.rider_name].filter(Boolean).join(' ') || '—',
      minWidth: 140,
      title: '骑手',
    },
    { field: 'biz_date', title: '日期', width: 120 },
    { field: 'distance_km', title: '距离', width: 90 },
    { field: 'weight_jin', title: '重量', width: 90 },
    { field: 'order_time', minWidth: 160, title: '下单' },
    { field: 'deliver_time', minWidth: 160, title: '送达' },
    {
      cellRender: {
        name: 'CellTag',
        options: enumTagOptions(ORDER_STATUS_OPTIONS),
      },
      field: 'status',
      title: '状态',
      width: 110,
    },
    {
      cellRender: {
        name: 'CellTag',
        options: enumTagOptions(ORDER_SOURCE_OPTIONS),
      },
      field: 'source',
      title: '来源',
      width: 80,
    },
    {
      field: 'is_locked',
      slots: { default: 'locked' },
      title: '锁账',
      width: 70,
    },
    {
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'order_no',
          nameTitle: '订单',
          onClick: onActionClick,
        },
        name: 'CellOperation',
        options: [
          {
            code: 'edit',
            show: (row: OrderResult) =>
              hasAccessByCodes(['rs:order:edit']) && !row.is_locked,
            text: '纠错',
          },
          {
            code: 'remove',
            show: (row: OrderResult) =>
              hasAccessByCodes(['rs:order:del']) && !row.is_locked,
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
