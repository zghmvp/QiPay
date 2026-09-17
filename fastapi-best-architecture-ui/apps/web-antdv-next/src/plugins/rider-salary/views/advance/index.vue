<script lang="ts" setup>
import type { VbenFormProps } from '@vben/common-ui';

import type { AdvanceQuery, AdvanceResult } from '../../types/advance';

import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';

import { onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';

import { confirm, useVbenDrawer, VbenButton } from '@vben/common-ui';

import { message } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';

import {
  approveAdvanceApi,
  cancelAdvanceApi,
  exportAdvancesApi,
  getAdvanceListApi,
  markPaidAdvanceApi,
  rejectAdvanceApi,
} from '../../api/advance';
import MoneyText from '../../components/MoneyText.vue';
import { useReasonModal } from '../../components/use-reason-modal';
import { monthRange, toDateString } from '../../utils/date';
import PageContainer from '../_shared/PageContainer.vue';
import AdvanceDrawer from './components/AdvanceDrawer.vue';
import { querySchema, useColumns } from './data';

function isUserCancelled(error: unknown) {
  const msg = (error as Error)?.message;
  return msg === 'cancelled' || msg === 'dialog cancelled';
}

const { ReasonModal, prompt } = useReasonModal();

const route = useRoute();
const ADVANCE_TABS = new Set(['all', 'paid', 'pending', 'to_pay']);

function queryStr(key: string) {
  const raw = route.query[key];
  const v = Array.isArray(raw) ? raw[0] : raw;
  return typeof v === 'string' && v ? v : undefined;
}

function queryNum(key: string) {
  const n = Number(queryStr(key));
  return Number.isFinite(n) && n > 0 ? n : undefined;
}

const initialStatus =
  typeof route.query.status === 'string' ? route.query.status : undefined;
const initialSiteId = queryNum('site_id');
const initialRiderId = queryNum('rider_id');
const initialId = queryNum('id');
const initialMonth = queryStr('month');
const initialDateRange = initialMonth ? monthRange(initialMonth) : undefined;
const tab = ref(
  initialId
    ? 'all'
    : !initialStatus
      ? 'pending'
      : ADVANCE_TABS.has(initialStatus)
        ? initialStatus
        : 'all',
);

const formOptions: VbenFormProps = {
  collapsed: true,
  schema: querySchema.map((item) => {
    if (
      item.fieldName === 'status' &&
      initialStatus &&
      !ADVANCE_TABS.has(initialStatus)
    ) {
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
    return item;
  }),
  showCollapseButton: true,
  submitButtonOptions: { content: '查询' },
};

const gridOptions: VxeTableGridOptions<AdvanceResult> = {
  columns: useColumns(onActionClick),
  emptyText: '暂无待审核的预支申请',
  height: 'auto',
  proxyConfig: {
    ajax: {
      query: async ({ page }, formValues) => {
        const { date_range, ...rest } = formValues as Record<string, unknown> & {
          date_range?: [string, string];
        };
        const status =
          tab.value === 'all'
            ? (rest.status as string | undefined)
            : tab.value;
        return await getAdvanceListApi({
          date_from: toDateString(date_range?.[0]),
          date_to: toDateString(date_range?.[1]),
          id: initialId,
          page: page.currentPage,
          size: page.pageSize,
          ...rest,
          status,
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

onMounted(async () => {
  const values: Record<string, unknown> = {};
  if (initialStatus && !ADVANCE_TABS.has(initialStatus)) {
    values.status = initialStatus;
  }
  if (initialSiteId) values.site_id = initialSiteId;
  if (initialRiderId) values.rider_id = initialRiderId;
  if (initialDateRange) values.date_range = initialDateRange;
  if (Object.keys(values).length) {
    await gridApi.formApi.setValues(values);
  }
});

function onRefresh() {
  gridApi.query();
}

function onTabChange(key: number | string) {
  tab.value = String(key);
  onRefresh();
}

async function currentFilters(): Promise<Omit<AdvanceQuery, 'page' | 'size'>> {
  const values = (await gridApi.formApi.getValues()) as Record<string, unknown> & {
    date_range?: [string, string];
  };
  const { date_range, ...rest } = values;
  return {
    date_from: toDateString(date_range?.[0]),
    date_to: toDateString(date_range?.[1]),
    ...rest,
    status: tab.value === 'all' ? (rest.status as string | undefined) : tab.value,
  };
}

async function onExport() {
  await exportAdvancesApi(await currentFilters());
}

async function onActionClick({
  code,
  row,
}: OnActionClickParams<AdvanceResult>) {
  try {
    if (code === 'detail') {
      detailApi.setData({ id: row.id }).open();
      return;
    }
    if (code === 'approve') {
      await confirm({
        content:
          '确认通过该预支申请？通过后需线下打款，再回来标记已发放。',
        icon: 'warning',
      });
      const { reason } = await prompt({
        reasonRequired: false,
        title: '审核备注（可选）',
      });
      await approveAdvanceApi(row.id, { remark: reason || undefined });
      message.success('已通过预支申请');
      onRefresh();
      return;
    }
    if (code === 'reject') {
      const { reason } = await prompt({ title: '驳回原因' });
      await rejectAdvanceApi(row.id, { reason });
      message.success('已驳回预支申请');
      onRefresh();
      return;
    }
    if (code === 'mark-paid') {
      await confirm({
        content: '确认已完成线下打款并标记为已发放？',
        icon: 'warning',
      });
      await markPaidAdvanceApi(row.id);
      message.success('已标记发放');
      onRefresh();
      return;
    }
    if (code === 'cancel') {
      const { reason } = await prompt({ title: '取消原因' });
      await cancelAdvanceApi(row.id, { reason });
      message.success('已取消预支');
      onRefresh();
    }
  } catch (error: unknown) {
    if (isUserCancelled(error)) return;
    throw error;
  }
}

const [DetailDrawer, detailApi] = useVbenDrawer({
  connectedComponent: AdvanceDrawer,
});
</script>

<template>
  <PageContainer>
    <a-tabs :active-key="tab" class="mb-2" @change="onTabChange">
      <a-tab-pane key="pending" tab="待审核" />
      <a-tab-pane key="to_pay" tab="待发放" />
      <a-tab-pane key="paid" tab="已发放" />
      <a-tab-pane key="all" tab="全部" />
    </a-tabs>
    <Grid>
      <template #toolbar-actions>
        <VbenButton v-access:code="'rs:advance:export'" @click="onExport">
          导出预支明细
        </VbenButton>
      </template>
      <template #amount="{ row }">
        <MoneyText :value="row.amount" />
      </template>
      <template #deducted="{ row }">
        <MoneyText :value="row.deducted_amount" />
      </template>
      <template #remaining="{ row }">
        <MoneyText :value="row.remaining_amount" />
      </template>
    </Grid>
    <DetailDrawer />
    <ReasonModal />
  </PageContainer>
</template>
