<script lang="ts" setup>
import type { VbenFormProps } from '@vben/common-ui';

import type { OrderResult } from '../../types/order';

import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';

import { onMounted } from 'vue';
import { useRoute } from 'vue-router';

import { useVbenDrawer, useVbenModal, VbenButton } from '@vben/common-ui';
import { IconifyIcon, MaterialSymbolsAdd } from '@vben/icons';

import { message } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';

import {
  deleteOrderApi,
  downloadImportTemplateApi,
  getOrderListApi,
} from '../../api/order';
import { useReasonModal } from '../../components/use-reason-modal';
import { toDateString } from '../../utils/date';
import PageContainer from '../_shared/PageContainer.vue';
import BatchList from './components/BatchList.vue';
import ImportWizard from './components/ImportWizard.vue';
import OrderForm from './components/OrderForm.vue';
import { querySchema, useColumns } from './data';

function isUserCancelled(error: unknown) {
  const msg = (error as Error)?.message;
  return msg === 'cancelled' || msg === 'dialog cancelled';
}

const route = useRoute();
const { ReasonModal, prompt } = useReasonModal();

const initialStatus =
  typeof route.query.status === 'string' ? route.query.status : undefined;

const formOptions: VbenFormProps = {
  collapsed: true,
  schema: querySchema.map((item) =>
    item.fieldName === 'status' && initialStatus
      ? { ...item, defaultValue: initialStatus }
      : item,
  ),
  showCollapseButton: true,
  submitButtonOptions: { content: '查询' },
};

const gridOptions: VxeTableGridOptions<OrderResult> = {
  columns: useColumns(onActionClick),
  emptyText: '暂无订单，请先导入或补录',
  height: 'auto',
  proxyConfig: {
    ajax: {
      query: async ({ page }, formValues) => {
        const { date_range, is_locked, ...rest } = formValues as Record<string, unknown> & {
          date_range?: [string, string];
          is_locked?: boolean | string;
        };
        let locked: boolean | undefined;
        if (is_locked === true || is_locked === 'true') locked = true;
        else if (is_locked === false || is_locked === 'false') locked = false;
        return await getOrderListApi({
          date_from: toDateString(date_range?.[0]),
          date_to: toDateString(date_range?.[1]),
          is_locked: locked,
          page: page.currentPage,
          size: page.pageSize,
          ...rest,
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

async function onActionClick({ code, row }: OnActionClickParams<OrderResult>) {
  if (code === 'edit') {
    formDrawerApi.setData({ ...row, onSuccess: onRefresh }).open();
    return;
  }
  if (code === 'remove') {
    try {
      const { reason } = await prompt({ title: '删除订单原因' });
      await deleteOrderApi(row.id, reason);
      message.success('已删除订单');
      onRefresh();
    } catch (error: unknown) {
      if (isUserCancelled(error)) return;
      throw error;
    }
  }
}

async function onDownloadTemplate() {
  await downloadImportTemplateApi();
}

async function onImported(batchId?: null | number) {
  if (batchId) {
    await gridApi.formApi.setValues({ import_batch_id: batchId });
  }
  onRefresh();
}

const [FormDrawer, formDrawerApi] = useVbenDrawer({
  connectedComponent: OrderForm,
});
const [WizardModal, wizardApi] = useVbenModal({
  connectedComponent: ImportWizard,
});
const [BatchDrawer, batchApi] = useVbenDrawer({
  connectedComponent: BatchList,
});

onMounted(() => {
  if (initialStatus) {
    void gridApi.formApi.setValues({ status: initialStatus });
  }
});
</script>

<template>
  <PageContainer>
    <Grid>
      <template #toolbar-actions>
        <VbenButton
          v-access:code="'rs:order:import'"
          class="mr-2"
          @click="() => wizardApi.setData({ onSuccess: onImported }).open()"
        >
          导入
        </VbenButton>
        <VbenButton
          v-access:code="'rs:order:import'"
          class="mr-2"
          @click="onDownloadTemplate"
        >
          下载模板
        </VbenButton>
        <VbenButton
          v-access:code="'rs:order:add'"
          class="mr-2"
          @click="() => formDrawerApi.setData({ onSuccess: onRefresh }).open()"
        >
          <MaterialSymbolsAdd class="size-5" />
          补录
        </VbenButton>
        <VbenButton @click="() => batchApi.open()">导入批次</VbenButton>
      </template>
      <template #locked="{ row }">
        <IconifyIcon
          v-if="row.is_locked"
          class="size-4 text-red-500"
          icon="lucide:lock"
        />
      </template>
    </Grid>
    <FormDrawer />
    <WizardModal />
    <BatchDrawer />
    <ReasonModal />
  </PageContainer>
</template>
