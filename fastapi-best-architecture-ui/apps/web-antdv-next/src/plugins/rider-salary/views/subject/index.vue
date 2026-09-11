<script lang="ts" setup>
import type { VbenFormProps } from '@vben/common-ui';

import type { SubjectForm, SubjectResult } from '../../types/subject';

import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';

import { computed, ref } from 'vue';

import { useVbenDrawer, VbenButton } from '@vben/common-ui';
import { MaterialSymbolsAdd } from '@vben/icons';

import { message } from 'antdv-next';

import { useVbenForm } from '#/adapter/form';
import { useVbenVxeGrid } from '#/adapter/vxe-table';

import {
  createSubjectApi,
  deleteSubjectApi,
  getSubjectListApi,
  updateSubjectApi,
} from '../../api/subject';
import MoneyText from '../../components/MoneyText.vue';
import PageContainer from '../_shared/PageContainer.vue';
import { querySchema, subjectFormSchema, useColumns } from './data';

const formOptions: VbenFormProps = {
  collapsed: true,
  schema: querySchema,
  showCollapseButton: true,
  submitButtonOptions: { content: '查询' },
};

const gridOptions: VxeTableGridOptions<SubjectResult> = {
  columns: useColumns(onActionClick),
  height: 'auto',
  proxyConfig: {
    ajax: {
      query: async ({ page }, formValues) => {
        return await getSubjectListApi({
          page: page.currentPage,
          size: page.pageSize,
          ...formValues,
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

function onActionClick({ code, row }: OnActionClickParams<SubjectResult>) {
  if (code === 'edit') {
    drawerApi.setData(row).open();
    return;
  }
  if (code === 'delete') {
    deleteSubjectApi(row.id)
      .then(() => {
        message.success(`已删除科目 ${row.name}`);
        onRefresh();
      })
      .catch(() => {
        /* 拦截器已弹出后端引用计数字段 */
      });
  }
}

const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  schema: subjectFormSchema,
  showDefaultActions: false,
});

const formData = ref<{ id?: number }>();
const drawerTitle = computed(() => (formData.value?.id ? '编辑科目' : '新增科目'));

const [Drawer, drawerApi] = useVbenDrawer({
  class: 'w-[480px]',
  destroyOnClose: true,
  async onConfirm() {
    const { valid } = await formApi.validate();
    if (!valid) return;
    const values = await formApi.getValues<SubjectForm & { is_builtin?: boolean }>();
    drawerApi.lock();
    try {
      const payload: SubjectForm = {
        code: values.code,
        direction: values.direction,
        entry_granularity: values.entry_granularity,
        fee_mode: values.fee_mode,
        fixed_amount: values.fixed_amount,
        include_in_gross: values.include_in_gross,
        name: values.name,
        remark: values.remark,
        sort_order: values.sort_order,
        status: values.status,
      };
      if (formData.value?.id) {
        await updateSubjectApi(formData.value.id, payload);
      } else {
        await createSubjectApi(payload);
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
    const data = drawerApi.getData<SubjectResult>();
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
          v-access:code="'rs:subject:add'"
          @click="() => drawerApi.setData(null).open()"
        >
          <MaterialSymbolsAdd class="size-5" />
          新增科目
        </VbenButton>
      </template>
      <template #fixed_amount="{ row }">
        <MoneyText :value="row.fixed_amount" />
      </template>
    </Grid>
    <Drawer :title="drawerTitle">
      <Form />
    </Drawer>
  </PageContainer>
</template>
