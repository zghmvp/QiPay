import type { NoticeResult } from '../../types/notice';

import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeGridProps } from '#/adapter/vxe-table';

import { h } from 'vue';

import { useAccess } from '@vben/access';

import SiteSelect from '../../components/SiteSelect.vue';
import { enumTagOptions, NOTICE_STATUS_OPTIONS } from '../../constants/enums';

export const querySchema: VbenFormSchema[] = [
  {
    component: 'Input',
    fieldName: 'title',
    label: '标题',
  },
  {
    component: h(SiteSelect),
    componentProps: { allowAll: true },
    fieldName: 'site_id',
    label: '站点',
    modelPropName: 'value',
  },
  {
    component: 'Select',
    componentProps: {
      allowClear: true,
      options: enumTagOptions(NOTICE_STATUS_OPTIONS),
    },
    fieldName: 'status',
    label: '状态',
  },
];

export const noticeFormSchema: VbenFormSchema[] = [
  {
    component: 'Input',
    fieldName: 'title',
    label: '标题',
    rules: 'required',
  },
  {
    component: h(SiteSelect),
    componentProps: { allowAll: true, allowClear: true },
    fieldName: 'site_id',
    label: '发布范围',
    modelPropName: 'value',
  },
  {
    component: 'Textarea',
    componentProps: { rows: 8 },
    fieldName: 'content',
    label: '正文',
    rules: 'required',
  },
];

export function useColumns(
  onActionClick?: OnActionClickFn<NoticeResult>,
): VxeGridProps['columns'] {
  const { hasAccessByCodes } = useAccess();
  return [
    { field: 'seq', title: '序号', type: 'seq', width: 60 },
    { field: 'title', minWidth: 180, title: '标题' },
    {
      field: 'site_id',
      formatter: ({ cellValue }: { cellValue: null | number }) =>
        cellValue ? `站点 #${cellValue}` : '全部站点',
      title: '范围',
      width: 120,
    },
    {
      cellRender: {
        name: 'CellTag',
        options: enumTagOptions(NOTICE_STATUS_OPTIONS),
      },
      field: 'status',
      title: '状态',
      width: 100,
    },
    { field: 'publish_time', title: '发布时间', width: 170 },
    {
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'title',
          nameTitle: '公告',
          onClick: onActionClick,
        },
        name: 'CellOperation',
        options: [
          {
            code: 'edit',
            show: () => hasAccessByCodes(['rs:notice:edit']),
            text: '编辑',
          },
          {
            code: 'publish',
            show: (row: NoticeResult) =>
              hasAccessByCodes(['rs:notice:edit']) && row.status !== 'published',
            text: '发布',
          },
          {
            code: 'offline',
            show: (row: NoticeResult) =>
              hasAccessByCodes(['rs:notice:edit']) && row.status === 'published',
            text: '下线',
          },
          {
            code: 'delete',
            show: () => hasAccessByCodes(['rs:notice:del']),
            text: '删除',
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
