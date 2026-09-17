<script lang="ts" setup>
import type { VbenFormProps } from '@vben/common-ui';

import type { PeriodResult } from '../../types/period';

import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';

import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import {
  confirm,
  useVbenDrawer,
  useVbenModal,
  VbenButton,
} from '@vben/common-ui';
import { MaterialSymbolsAdd } from '@vben/icons';

import { message } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';

import {
  deletePeriodApi,
  exportPeriodApi,
  getPeriodApi,
  getPeriodListApi,
  lockPeriodApi,
  markPaidPeriodApi,
  reversePeriodApi,
} from '../../api/period';
import MoneyText from '../../components/MoneyText.vue';
import { useReasonModal } from '../../components/use-reason-modal';
import PageContainer from '../_shared/PageContainer.vue';
import GenerateModal from './components/GenerateModal.vue';
import PeriodDetail from './components/PeriodDetail.vue';
import { querySchema, useColumns } from './data';

function isUserCancelled(error: unknown) {
  const msg = (error as Error)?.message;
  return msg === 'cancelled' || msg === 'dialog cancelled';
}

const route = useRoute();
const router = useRouter();
const { ReasonModal, prompt } = useReasonModal();
const onlyStale = ref(
  route.query.stale === '1' || route.query.stale === 'true',
);

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

const gridOptions: VxeTableGridOptions<PeriodResult> = {
  columns: useColumns(onActionClick),
  emptyText: '还没有结算周期，请先生成周期或导入后算薪',
  height: 'auto',
  proxyConfig: {
    ajax: {
      query: async ({ page }, formValues) => {
        const res = await getPeriodListApi({
          page: page.currentPage,
          size: page.pageSize,
          ...(formValues as {
            month?: string;
            rider_id?: number;
            site_id?: number;
            status?: string;
          }),
        });
        if (!onlyStale.value) return res;
        const items = (res?.items ?? []).filter(
          (item) => (item.stale_count ?? 0) > 0,
        );
        return { ...res, items, total: items.length };
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

const staleHint = computed(() =>
  onlyStale.value ? '已按工作台跳转筛选：需重算周期' : '',
);

function onRefresh() {
  gridApi.query();
}

function openDetail(row: PeriodResult) {
  detailApi.setData({ id: row.id }).open();
}

async function onLock(row: PeriodResult) {
  if (!(row.payroll_count ?? 0)) {
    await confirm({
      content: '当前周期没有薪资结果，仍要锁账吗？',
      icon: 'warning',
    });
  }
  const { reason } = await prompt({
    extraHint: `将冻结本周期订单、奖惩与薪资结果（骑手 ${row.rider_count ?? 0}，薪资单 ${row.payroll_count ?? 0}）。若存在需重算结果，后端会拒绝并列出工号。`,
    title: '锁账原因',
  });
  await lockPeriodApi(row.id, reason);
  message.success('已锁账');
  onRefresh();
}

async function onMarkPaid(row: PeriodResult) {
  await confirm({
    content: '确认将该周期标记为已发薪？此操作仅标记，不涉及实际打款。',
    icon: 'warning',
  });
  await markPaidPeriodApi(row.id);
  message.success('已标记发薪');
  onRefresh();
}

async function onReverse(row: PeriodResult) {
  await confirm({
    content:
      '将为已定稿/已发薪的薪资单生成反冲单，原单标记已反冲，周期进入补发中。确认继续？',
    icon: 'warning',
  });
  const { reason } = await prompt({
    extraHint: '反冲后需重新算薪才会生成补发单。',
    title: '反冲补发原因',
  });
  const res = await reversePeriodApi(row.id, reason);
  message.success(`已生成 ${res.reversal_count} 张反冲单`);
  onRefresh();
}

async function onActionClick({
  code,
  row,
}: OnActionClickParams<PeriodResult>) {
  try {
    if (code === 'detail') {
      openDetail(row);
      return;
    }
    if (code === 'calculate') {
      router.push({
        path: `/rider-salary/period/${row.id}/calculate`,
      });
      return;
    }
    if (code === 'lock') {
      await onLock(row);
      return;
    }
    if (code === 'mark-paid') {
      await onMarkPaid(row);
      return;
    }
    if (code === 'reverse') {
      await onReverse(row);
      return;
    }
    if (code === 'export') {
      await exportPeriodApi(row.id);
      return;
    }
    if (code === 'remove') {
      await confirm({
        content: `确认删除周期 ${row.start_date} ~ ${row.end_date}？仅开放且无薪资结果的周期可删。`,
        icon: 'warning',
      });
      await deletePeriodApi(row.id);
      message.success('已删除周期');
      onRefresh();
    }
  } catch (error: unknown) {
    if (isUserCancelled(error)) return;
    throw error;
  }
}

const [DetailDrawer, detailApi] = useVbenDrawer({
  connectedComponent: PeriodDetail,
});
const [GenModal, genApi] = useVbenModal({
  connectedComponent: GenerateModal,
});

function queryId(): number | undefined {
  const raw = route.query.id;
  const v = Array.isArray(raw) ? raw[0] : raw;
  const id = Number(v);
  return Number.isFinite(id) && id > 0 ? id : undefined;
}

function currentPeriodRows(): PeriodResult[] {
  const data = gridApi.grid.getTableData?.();
  return (data?.fullData ?? data?.tableData ?? []) as PeriodResult[];
}

function selectPeriodRow(id: number) {
  const row = currentPeriodRows().find((item) => item.id === id);
  if (row) {
    gridApi.grid.setCurrentRow?.(row);
  }
  return row;
}

let openedQueryId: number | undefined;

async function openPeriodByQueryId() {
  const id = queryId();
  if (!id || openedQueryId === id) return;
  openedQueryId = id;
  await nextTick();
  await gridApi.query();
  if (!selectPeriodRow(id)) {
    try {
      const detail = await getPeriodApi(id);
      onlyStale.value = false;
      await gridApi.formApi.setValues({
        site_id: detail.site_id,
        status: detail.status,
      });
      await gridApi.query();
      selectPeriodRow(id);
    } catch {
      openedQueryId = undefined;
      return;
    }
  }
  detailApi.setData({ id }).open();
}

watch(
  () => route.query.id,
  () => {
    void openPeriodByQueryId();
  },
);

onMounted(() => {
  if (initialStatus) {
    void gridApi.formApi.setValues({ status: initialStatus });
  }
  void openPeriodByQueryId();
});
</script>

<template>
  <PageContainer>
    <a-alert
      v-if="staleHint"
      class="mb-2"
      closable
      show-icon
      type="warning"
      :message="staleHint"
      @close="onlyStale = false"
    />
    <Grid>
      <template #toolbar-actions>
        <VbenButton
          v-access:code="'rs:period:generate'"
          @click="() => genApi.setData({ onSuccess: onRefresh }).open()"
        >
          <MaterialSymbolsAdd class="size-5" />
          生成周期
        </VbenButton>
      </template>
      <template #stale="{ row }">
        <span :class="row.stale_count ? 'font-medium text-red-500' : ''">
          {{ row.stale_count ?? 0 }}
        </span>
      </template>
      <template #gross="{ row }">
        <MoneyText :value="row.gross_total" />
      </template>
      <template #net="{ row }">
        <MoneyText :value="row.net_total" />
      </template>
    </Grid>
    <DetailDrawer />
    <GenModal />
    <ReasonModal />
  </PageContainer>
</template>
