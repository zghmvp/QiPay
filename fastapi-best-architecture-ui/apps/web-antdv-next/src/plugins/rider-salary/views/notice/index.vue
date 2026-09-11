<script lang="ts" setup>
import type { VbenFormProps } from '@vben/common-ui';

import type { NoticeForm, NoticeResult } from '../../types/notice';

import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';

import { computed, ref } from 'vue';

import { confirm, useVbenDrawer, VbenButton } from '@vben/common-ui';
import { MaterialSymbolsAdd } from '@vben/icons';

import { message } from 'antdv-next';

import { useVbenForm } from '#/adapter/form';
import { useVbenVxeGrid } from '#/adapter/vxe-table';

import {
  createNoticeApi,
  deleteNoticeApi,
  getNoticeListApi,
  offlineNoticeApi,
  publishNoticeApi,
  updateNoticeApi,
} from '../../api/notice';
import PageContainer from '../_shared/PageContainer.vue';
import { noticeFormSchema, querySchema, useColumns } from './data';

const formOptions: VbenFormProps = {
  collapsed: true,
  schema: querySchema,
  showCollapseButton: true,
  submitButtonOptions: { content: '查询' },
};

const gridOptions: VxeTableGridOptions<NoticeResult> = {
  columns: useColumns(onActionClick),
  height: 'auto',
  proxyConfig: {
    ajax: {
      query: async ({ page }, formValues) => {
        const values = { ...(formValues as Record<string, unknown>) };
        if (values.site_id === null || values.site_id === 0) {
          delete values.site_id;
        }
        return await getNoticeListApi({
          page: page.currentPage,
          size: page.pageSize,
          ...(values as {
            site_id?: number;
            status?: string;
            title?: string;
          }),
        });
      },
    },
  },
  rowConfig: { keyField: 'id' },
  toolbarConfig: {
    custom: true,
    refresh: true,
    refreshOptions: { code: 'query' },
  },
};

const [Grid, gridApi] = useVbenVxeGrid({ formOptions, gridOptions });

function onRefresh() {
  gridApi.query();
}

async function onActionClick({ code, row }: OnActionClickParams<NoticeResult>) {
  if (code === 'edit') {
    drawerApi.setData(row).open();
    return;
  }
  if (code === 'publish') {
    if (!row.site_id) {
      await confirm({
        content: '该公告将向全部站点骑手展示',
        icon: 'warning',
      });
    }
    await publishNoticeApi(row.id);
    message.success('已发布');
    onRefresh();
    return;
  }
  if (code === 'offline') {
    await offlineNoticeApi(row.id);
    message.success('已下线');
    onRefresh();
    return;
  }
  if (code === 'delete') {
    await deleteNoticeApi(row.id);
    message.success(`已删除公告 ${row.title}`);
    onRefresh();
  }
}

const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  schema: noticeFormSchema,
  showDefaultActions: false,
});

const formData = ref<{ id?: number }>();
const drawerTitle = computed(() => (formData.value?.id ? '编辑公告' : '新增公告'));

const [Drawer, drawerApi] = useVbenDrawer({
  class: 'w-[560px]',
  destroyOnClose: true,
  async onConfirm() {
    const { valid } = await formApi.validate();
    if (!valid) return;
    const values = await formApi.getValues<NoticeForm>();
    const payload: NoticeForm = {
      content: values.content,
      site_id: values.site_id || null,
      title: values.title,
    };
    drawerApi.lock();
    try {
      if (formData.value?.id) {
        await updateNoticeApi(formData.value.id, payload);
      } else {
        await createNoticeApi(payload);
      }
      message.success('操作成功');
      await drawerApi.close();
      onRefresh();
    } finally {
      drawerApi.unlock();
    }
  },
  onOpenChange(isOpen) {
    if (!isOpen) return;
    const data = drawerApi.getData<NoticeResult>();
    formApi.resetForm();
    if (data?.id) {
      formData.value = { id: data.id };
      formApi.setValues(data);
    } else {
      formData.value = undefined;
    }
  },
});
</script>

<template>
  <PageContainer>
    <Grid>
      <template #toolbar-actions>
        <VbenButton
          v-access:code="'rs:notice:add'"
          @click="() => drawerApi.setData(null).open()"
        >
          <MaterialSymbolsAdd class="size-5" />
          新增公告
        </VbenButton>
      </template>
    </Grid>
    <Drawer :title="drawerTitle">
      <Form />
    </Drawer>
  </PageContainer>
</template>
