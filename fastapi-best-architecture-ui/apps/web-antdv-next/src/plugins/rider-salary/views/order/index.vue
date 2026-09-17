<script lang="ts" setup>
import type { VbenFormProps } from '@vben/common-ui';

import type { RecalcJobDetail } from '../../types/dashboard';
import type { OrderResult } from '../../types/order';

import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';

import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { useAccess } from '@vben/access';
import { useVbenDrawer, useVbenModal, VbenButton } from '@vben/common-ui';
import { IconifyIcon, MaterialSymbolsAdd } from '@vben/icons';

import { message } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';

import { fetchLatestSiteRecalcJob } from '../../api/dashboard';
import {
  deleteOrderApi,
  downloadImportTemplateApi,
  getOrderListApi,
} from '../../api/order';
import RecalcJobCard from '../../components/RecalcJobCard.vue';
import { useReasonModal } from '../../components/use-reason-modal';
import { toDateString } from '../../utils/date';
import {
  readLastImportCalcTarget,
  readLastRecalcJob,
} from '../../utils/last-recalc-job';
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
const router = useRouter();
const { hasAccessByCodes } = useAccess();
const { ReasonModal, prompt } = useReasonModal();
const lastRecalcJob = ref<RecalcJobDetail>();
const lastImportPeriodIds = ref<number[]>([]);
const canViewRecalcJob = computed(() =>
  hasAccessByCodes(['rs:period:calculate']),
);

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
const initialMissingDelivery =
  route.query.missing_delivery === '1' ||
  route.query.missing_delivery === 'true';

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
    if (item.fieldName === 'missing_delivery' && initialMissingDelivery) {
      return { ...item, defaultValue: true };
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
        const { date_range, is_locked, status, missing_delivery, ...rest } =
          formValues as Record<string, unknown> & {
            date_range?: [string, string];
            is_locked?: boolean | string;
            missing_delivery?: boolean | string;
            status?: string;
          };
        let locked: boolean | undefined;
        if (is_locked === true || is_locked === 'true') locked = true;
        else if (is_locked === false || is_locked === 'false') locked = false;
        const attention = status === '__attention__';
        const missing =
          missing_delivery === true || missing_delivery === 'true';
        return await getOrderListApi({
          attention: attention || undefined,
          date_from: toDateString(date_range?.[0]),
          date_to: toDateString(date_range?.[1]),
          is_locked: locked,
          missing_delivery: missing || undefined,
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
  await loadLastRecalcJob();
  onRefresh();
}

async function loadLastRecalcJob() {
  const siteId = initialSiteId || readLastRecalcJob()?.siteId;
  lastImportPeriodIds.value =
    readLastImportCalcTarget(siteId)?.periodIds ?? [];
  if (!siteId || !canViewRecalcJob.value) {
    lastRecalcJob.value = undefined;
    return;
  }
  lastRecalcJob.value = (await fetchLatestSiteRecalcJob(siteId)) ?? undefined;
}

function goStoredCalc(periodId: number) {
  void router.push({ path: `/rider-salary/period/${periodId}/calculate` });
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
  if (initialMissingDelivery) values.missing_delivery = true;
  if (Object.keys(values).length) {
    void gridApi.formApi.setValues(values);
  }
  void loadLastRecalcJob();
});
</script>

<template>
  <PageContainer>
    <div
      v-if="lastRecalcJob || lastImportPeriodIds.length"
      class="mb-2"
      data-testid="order-last-recalc"
    >
      <RecalcJobCard
        v-if="lastRecalcJob"
        testid-prefix="order-recalc-job"
        :job="lastRecalcJob"
      />
      <a-alert
        v-else
        show-icon
        type="warning"
        data-testid="import-not-payroll"
        message="导入完成 ≠ 已出账"
        description="订单已入库，须到周期算薪页计算后才有薪资结果。"
      >
        <template #action>
          <a-button
            v-for="pid in lastImportPeriodIds"
            :key="pid"
            size="small"
            type="link"
            data-testid="import-goto-calculate"
            @click="goStoredCalc(pid)"
          >
            去周期算薪页
          </a-button>
        </template>
      </a-alert>
    </div>
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
