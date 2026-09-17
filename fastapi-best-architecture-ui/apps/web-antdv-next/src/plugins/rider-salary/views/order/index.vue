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

function queryStr(key: string) {
  const raw = route.query[key];
  const v = Array.isArray(raw) ? raw[0] : raw;
  return typeof v === 'string' && v ? v : undefined;
}

function queryNum(key: string) {
  const n = Number(queryStr(key));
  return Number.isFinite(n) && n > 0 ? n : undefined;
}

const initialAttention =
  route.query.attention === '1' ||
  route.query.attention === 'true' ||
  queryStr('status') === '__attention__';
const initialStatus = initialAttention
  ? '__attention__'
  : queryStr('status');
const initialSiteId = queryNum('site_id');
const initialRiderId = queryNum('rider_id');
const initialDate = queryStr('date');
const initialDateFrom = queryStr('date_from');
const initialDateTo = queryStr('date_to');
const initialOrderNo = queryStr('order_no');

const initialDateRange =
  initialDateFrom && initialDateTo
    ? [initialDateFrom, initialDateTo]
    : initialDate
      ? [initialDate, initialDate]
      : undefined;

const formOptions: VbenFormProps = {
  collapsed: true,
  schema: querySchema.map((item) => {
    if (item.fieldName === 'status' && initialStatus) {
      return { ...item, defaultValue: initialStatus };
    }
    if (item.fieldName === 'site_id' && initialSiteId) {
      return { ...item, defaultValue: initialSiteId };
    }
    if (item.fieldName === 'rider_id' && initialRiderId) {
      return { ...item, defaultValue: initialRiderId };
    }
    if (item.fieldName === 'date_range' && initialDateRange) {
      return { ...item, defaultValue: initialDateRange };
    }
    if (item.fieldName === 'order_no' && initialOrderNo) {
      return { ...item, defaultValue: initialOrderNo };
    }
    return item;
  }),
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
        const { date_range, is_locked, status, ...rest } = formValues as Record<
          string,
          unknown
        > & {
          date_range?: [string, string];
          is_locked?: boolean | string;
          status?: string;
        };
        let locked: boolean | undefined;
        if (is_locked === true || is_locked === 'true') locked = true;
        else if (is_locked === false || is_locked === 'false') locked = false;
        const attention = status === '__attention__';
        return await getOrderListApi({
          attention: attention || undefined,
          date_from: toDateString(date_range?.[0]),
          date_to: toDateString(date_range?.[1]),
          is_locked: locked,
          page: page.currentPage,
          size: page.pageSize,
          status: attention ? undefined : status,
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
  const values: Record<string, unknown> = {};
  if (initialStatus) values.status = initialStatus;
  if (initialSiteId) values.site_id = initialSiteId;
  if (initialRiderId) values.rider_id = initialRiderId;
  if (initialDateRange) values.date_range = initialDateRange;
  if (initialOrderNo) values.order_no = initialOrderNo;
  if (Object.keys(values).length) {
    void gridApi.formApi.setValues(values);
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
