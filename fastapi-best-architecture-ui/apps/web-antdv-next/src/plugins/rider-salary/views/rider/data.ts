import type { RiderResult } from '../../types/rider';

import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeGridProps } from '#/adapter/vxe-table';

import { h } from 'vue';

import { useAccess } from '@vben/access';

import dayjs from 'dayjs';

import SiteSelect from '../../components/SiteSelect.vue';
import {
  CYCLE_TYPE_OPTIONS,
  EMPLOY_TYPE_OPTIONS,
  enumTagOptions,
  RIDER_STATUS_OPTIONS,
} from '../../constants/enums';

const hireDatePresets = [
  { label: '今天', value: () => [dayjs(), dayjs()] },
  {
    label: '近7天',
    value: () => [dayjs().subtract(6, 'day'), dayjs()],
  },
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
    component: 'Input',
    componentProps: {
      allowClear: true,
      placeholder: '工号或姓名',
    },
    fieldName: 'keyword',
    label: '工号/姓名',
  },
  {
    component: 'Input',
    componentProps: {
      allowClear: true,
      placeholder: '手机号',
    },
    fieldName: 'phone',
    label: '手机',
  },
  {
    component: 'Select',
    componentProps: {
      allowClear: true,
      options: enumTagOptions(RIDER_STATUS_OPTIONS),
      placeholder: '全部状态',
    },
    fieldName: 'status',
    label: '在职状态',
  },
  {
    component: 'Select',
    componentProps: {
      allowClear: true,
      options: enumTagOptions(EMPLOY_TYPE_OPTIONS),
      placeholder: '全部类型',
    },
    fieldName: 'employ_type',
    label: '用工类型',
  },
  {
    component: 'RangePicker',
    componentProps: {
      allowClear: true,
      format: 'YYYY-MM-DD',
      placeholder: ['入职开始', '入职结束'],
      presets: hireDatePresets,
      style: { width: '100%' },
      valueFormat: 'YYYY-MM-DD',
    },
    fieldName: 'hire_range',
    formItemClass: 'md:col-span-2',
    label: '入职日期',
  },
  {
    component: 'Select',
    componentProps: {
      allowClear: true,
      options: [
        { label: '未开通', value: 'none' },
        { label: '启用', value: '1' },
        { label: '停用', value: '0' },
      ],
      placeholder: '全部账号',
    },
    fieldName: 'account_status',
    label: '账号状态',
  },
  {
    component: 'Select',
    componentProps: {
      allowClear: true,
      options: [
        { label: '跟随站点', value: 'inherit' },
        ...enumTagOptions(CYCLE_TYPE_OPTIONS),
      ],
      placeholder: '全部周期',
    },
    fieldName: 'settle_cycle_override',
    label: '结算周期',
  },
];

export const riderFormSchema: VbenFormSchema[] = [
  {
    component: 'Input',
    fieldName: 'job_no',
    label: '工号',
    rules: 'required',
  },
  {
    component: 'Input',
    fieldName: 'name',
    label: '姓名',
    rules: 'required',
  },
  {
    component: 'Input',
    fieldName: 'phone',
    label: '手机',
  },
  {
    component: h(SiteSelect),
    fieldName: 'site_id',
    label: '所属站点',
    modelPropName: 'value',
    rules: 'selectRequired',
  },
  {
    component: 'Select',
    componentProps: {
      options: enumTagOptions(EMPLOY_TYPE_OPTIONS),
    },
    defaultValue: 'part_time',
    fieldName: 'employ_type',
    label: '用工类型',
    rules: 'selectRequired',
  },
  {
    component: 'DatePicker',
    componentProps: {
      format: 'YYYY-MM-DD',
      style: { width: '100%' },
      valueFormat: 'YYYY-MM-DD',
    },
    fieldName: 'hire_date',
    label: '入职日期',
    rules: 'required',
  },
  {
    component: 'InputNumber',
    componentProps: {
      min: 0,
      precision: 2,
      style: { width: '100%' },
    },
    fieldName: 'advance_limit',
    label: '预支上限',
  },
  {
    component: 'Select',
    componentProps: {
      allowClear: true,
      options: enumTagOptions(CYCLE_TYPE_OPTIONS),
    },
    fieldName: 'settle_cycle_override',
    label: '结算周期覆盖',
  },
  {
    component: 'Select',
    componentProps: {
      options: enumTagOptions(RIDER_STATUS_OPTIONS),
    },
    defaultValue: 'on_job',
    fieldName: 'status',
    label: '状态',
  },
  {
    component: 'Textarea',
    fieldName: 'remark',
    label: '备注',
  },
];

export const bindingFormSchema: VbenFormSchema[] = [
  {
    component: 'Select',
    fieldName: 'plan_version_id',
    label: '方案版本',
    rules: 'selectRequired',
  },
  {
    component: 'Select',
    componentProps: {
      options: [
        { label: '默认', value: 'default' },
        { label: '区间覆盖', value: 'override' },
      ],
    },
    defaultValue: 'default',
    fieldName: 'binding_type',
    label: '绑定类型',
    rules: 'selectRequired',
  },
  {
    component: 'DatePicker',
    componentProps: {
      format: 'YYYY-MM-DD',
      style: { width: '100%' },
      valueFormat: 'YYYY-MM-DD',
    },
    fieldName: 'start_date',
    label: '开始日期',
    rules: 'required',
  },
  {
    component: 'DatePicker',
    componentProps: {
      format: 'YYYY-MM-DD',
      style: { width: '100%' },
      valueFormat: 'YYYY-MM-DD',
    },
    fieldName: 'end_date',
    label: '结束日期',
  },
  {
    component: 'Textarea',
    fieldName: 'remark',
    label: '备注',
  },
];

export const employFormSchema: VbenFormSchema[] = [
  {
    component: 'Select',
    componentProps: {
      options: enumTagOptions(EMPLOY_TYPE_OPTIONS),
    },
    fieldName: 'employ_type',
    label: '用工类型',
    rules: 'selectRequired',
  },
  {
    component: 'DatePicker',
    componentProps: {
      format: 'YYYY-MM-DD',
      style: { width: '100%' },
      valueFormat: 'YYYY-MM-DD',
    },
    fieldName: 'start_date',
    label: '开始日期',
    rules: 'required',
  },
  {
    component: 'DatePicker',
    componentProps: {
      format: 'YYYY-MM-DD',
      style: { width: '100%' },
      valueFormat: 'YYYY-MM-DD',
    },
    fieldName: 'end_date',
    label: '结束日期',
  },
  {
    component: 'Textarea',
    fieldName: 'remark',
    label: '备注',
  },
];

export function useColumns(
  onActionClick?: OnActionClickFn<RiderResult>,
): VxeGridProps['columns'] {
  const { hasAccessByCodes } = useAccess();
  return [
    { field: 'seq', title: '序号', type: 'seq', width: 60 },
    { field: 'job_no', title: '工号', width: 110 },
    { field: 'name', title: '姓名', width: 100 },
    { field: 'site_name', minWidth: 120, title: '站点' },
    {
      cellRender: {
        name: 'CellTag',
        options: enumTagOptions(EMPLOY_TYPE_OPTIONS),
      },
      field: 'employ_type',
      title: '用工类型',
      width: 100,
    },
    {
      cellRender: {
        name: 'CellTag',
        options: enumTagOptions(RIDER_STATUS_OPTIONS),
      },
      field: 'status',
      title: '状态',
      width: 90,
    },
    {
      field: 'plan_short_name',
      minWidth: 140,
      slots: { default: 'plan' },
      title: '当前方案',
    },
    {
      field: 'account_status_label',
      title: '账号状态',
      width: 100,
    },
    {
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'name',
          nameTitle: '骑手',
          onClick: onActionClick,
        },
        name: 'CellOperation',
        options: [
          {
            code: 'profile',
            text: '档案',
          },
          {
            code: 'edit',
            show: () => hasAccessByCodes(['rs:rider:edit']),
            text: '编辑',
          },
          {
            code: 'more',
            items: [
              {
                code: 'binding',
                show: () => hasAccessByCodes(['rs:rider:binding']),
                text: '方案绑定',
              },
              {
                code: 'employ',
                show: () => hasAccessByCodes(['rs:rider:employ']),
                text: '用工类型',
              },
              {
                code: 'open-account',
                show: (row: RiderResult) =>
                  hasAccessByCodes(['rs:rider:account']) && !row.user_id,
                text: '开通账号',
              },
              {
                code: 'reset-password',
                show: (row: RiderResult) =>
                  hasAccessByCodes(['rs:rider:account']) && Boolean(row.user_id),
                text: '重置密码',
              },
              {
                code: 'disable-account',
                show: (row: RiderResult) =>
                  hasAccessByCodes(['rs:rider:account']) &&
                  row.user_id &&
                  row.account_status === 1,
                text: '停用账号',
              },
              {
                code: 'enable-account',
                show: (row: RiderResult) =>
                  hasAccessByCodes(['rs:rider:account']) &&
                  row.user_id &&
                  row.account_status === 0,
                text: '启用账号',
              },
              {
                code: 'leave',
                show: (row: RiderResult) =>
                  hasAccessByCodes(['rs:rider:edit']) && row.status === 'on_job',
                text: '离职',
              },
            ],
            text: '更多',
          },
          {
            code: 'delete',
            show: () => hasAccessByCodes(['rs:rider:del']),
            text: '删除',
          },
        ],
      },
      field: 'operation',
      fixed: 'right',
      title: '操作',
      width: 210,
    },
  ];
}
