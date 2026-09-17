<script lang="ts" setup>
import type { VbenFormProps } from '@vben/common-ui';

import type { CalcPrecheckResult, PeriodResult, PeriodWithPayrolls } from '../../types/period';

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
  calcPrecheckApi,
  deletePeriodApi,
  exportPeriodApi,
  getPeriodApi,
  getPeriodListApi,
  lockPeriodApi,
  lockPreflightPeriodApi,
  markPaidPeriodApi,
  reversePeriodApi,
} from '../../api/period';
import MoneyText from '../../components/MoneyText.vue';
import { useReasonModal } from '../../components/use-reason-modal';
import PageContainer from '../_shared/PageContainer.vue';
import {
  periodStaleListParams,
  stalePeriodCalcTarget,
} from '../dashboard/scope-links';
import GenerateModal from './components/GenerateModal.vue';
import PeriodDetail from './components/PeriodDetail.vue';
import { useExportConfirm } from './components/use-export-confirm';
import { querySchema, useColumns } from './data';
import {
  SITE_LEVEL_LOCK_PREFLIGHT_FALLBACK,
  buildLockConfirmHint,
  isSiteLevelPeriod,
} from './lock-confirm';
import {
  countReverseTargets,
  reverseConfirmContent,
} from './reverse-confirm';

function isUserCancelled(error: unknown) {
  const msg = (error as Error)?.message;
  return msg === 'cancelled' || msg === 'dialog cancelled';
}

const route = useRoute();
const router = useRouter();
const { ReasonModal, prompt } = useReasonModal();
const { ExportConfirmModal, prompt: promptExport } = useExportConfirm();
const onlyStale = ref(
  route.query.stale === '1' || route.query.stale === 'true',
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

const initialStatus = queryStr('status');
const initialSiteId = queryNum('site_id');
const initialMonth = queryStr('month');
const lockDue =
  route.query.lock_due === '1' || route.query.lock_due === 'true';

const formOptions: VbenFormProps = {
  collapsed: true,
  schema: querySchema.map((item) => {
    if (item.fieldName === 'status' && initialStatus && !lockDue) {
      return { ...item, defaultValue: initialStatus };
    }
    if (item.fieldName === 'site_id' && initialSiteId) {
      return { ...item, defaultValue: initialSiteId };
    }
    if (item.fieldName === 'month' && initialMonth) {
      return { ...item, defaultValue: initialMonth };
    }
    return item;
  }),
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
        const values = formValues as {
          month?: string;
          rider_id?: number;
          site_id?: number;
          status?: string;
        };
        const siteId = Number(values.site_id) || initialSiteId;
        const month = values.month || initialMonth;
        return await getPeriodListApi({
          page: page.currentPage,
          size: page.pageSize,
          ...values,
          ...(onlyStale.value
            ? periodStaleListParams(siteId, month)
            : {
                ...(Number.isFinite(siteId) && siteId > 0
                  ? { site_id: siteId }
                  : {}),
                ...(month ? { month } : {}),
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

const staleHint = computed(() =>
  onlyStale.value ? '已按工作台跳转筛选：需重算周期' : '',
);
const missingPayrollHint = computed(() =>
  route.query.from === 'payroll-missing'
    ? '薪资单不存在或未落库。请打开对应周期的算薪页查看失败清单。'
    : '',
);
const lockDueHint = computed(() =>
  lockDue
    ? '已按工作台锁账倒计时跳转：本站开放/补发中周期，含已过期未锁。不是只看无月份的开放第一页。'
    : '',
);
const periodScopeHint = computed(() => {
  if (lockDueHint.value) return '';
  if (initialSiteId && initialMonth) {
    return `已按工作台跳转筛选：站点 + ${initialMonth}`;
  }
  if (initialMonth) return `已按工作台跳转筛选：${initialMonth}`;
  return '';
});
const lockFailText = ref('');

function extractErrorMsg(error: unknown): string {
  const err = error as {
    message?: string;
    msg?: string;
    response?: { data?: { data?: { errors?: string[] }; msg?: string } };
  };
  const dataErrors = err.response?.data?.data?.errors;
  if (Array.isArray(dataErrors) && dataErrors.length) {
    return dataErrors.join('；');
  }
  return (
    err.response?.data?.msg ||
    err.msg ||
    err.message ||
    ''
  );
}

function isHardFailCopy(text: string) {
  return /无生效方案|已完成但送达时间为空|从未成功落库|锁账中止|未算出的有单骑手|缺送达/.test(
    text,
  );
}

function collectHardFailLines(
  pre?: CalcPrecheckResult,
  detail?: null | PeriodWithPayrolls,
): string[] {
  const lines: string[] = [];
  for (const blocker of pre?.blockers ?? []) {
    for (const msg of blocker.messages ?? []) {
      if (isHardFailCopy(msg) || ['missing_delivery', 'no_plan_with_orders', 'never_calculated'].includes(blocker.code)) {
        lines.push(msg);
      }
    }
  }
  for (const fail of detail?.last_calc_failures ?? []) {
    for (const msg of fail.errors ?? []) {
      if (isHardFailCopy(msg)) lines.push(msg);
    }
  }
  return [...new Set(lines.filter(Boolean))];
}

function onRefresh() {
  gridApi.query();
}

function openDetail(row: PeriodResult) {
  detailApi.setData({ id: row.id }).open();
}

async function onLock(row: PeriodResult) {
  lockFailText.value = '';
  const [pre, detail] = await Promise.all([
    calcPrecheckApi(row.id),
    getPeriodApi(row.id).catch(() => null),
  ]);
  const hardLines = collectHardFailLines(pre, detail);
  const staleCount = pre.stale_count ?? detail?.stale_count ?? row.stale_count ?? 0;
  if (hardLines.length) {
    const staleTail = staleCount > 0 ? '。另有需重算草稿，请先重算。' : '';
    lockFailText.value = `不能锁账：${hardLines.join('；')}${staleTail}`;
    message.error(lockFailText.value);
    return;
  }
  let extraHint = `将冻结本周期订单、奖惩与薪资结果（骑手 ${row.rider_count ?? 0}，薪资单 ${row.payroll_count ?? 0}）。有完成单却未算出的骑手会被拒绝。`;
  let extraHintTestId: string | undefined;
  if (isSiteLevelPeriod(row)) {
    extraHintTestId = 'period-lock-skip-hint';
    try {
      extraHint = buildLockConfirmHint(await lockPreflightPeriodApi(row.id));
    } catch {
      extraHint = SITE_LEVEL_LOCK_PREFLIGHT_FALLBACK;
    }
  }
  const { reason } = await prompt({
    extraHint,
    extraHintTestId,
    title: '锁账原因',
  });
  try {
    await lockPeriodApi(row.id, reason);
    message.success('已锁账');
    onRefresh();
  } catch (error: unknown) {
    if (isUserCancelled(error)) return;
    const msg = extractErrorMsg(error);
    const extraHard = collectHardFailLines(pre, detail);
    if (extraHard.length && /请先重算/.test(msg) && !isHardFailCopy(msg)) {
      lockFailText.value = `不能锁账：${extraHard.join('；')}`;
    } else if (isHardFailCopy(msg)) {
      lockFailText.value = msg;
    } else {
      lockFailText.value = msg || '锁账失败';
    }
    throw error;
  }
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
  const detail = await getPeriodApi(row.id);
  const counts = countReverseTargets(detail.payrolls ?? []);
  await confirm({
    content: reverseConfirmContent(counts),
    icon: 'warning',
  });
  const { reason } = await prompt({
    extraHint: reverseConfirmContent(counts),
    title: '反冲补发原因',
  });
  const res = await reversePeriodApi(row.id, reason);
  message.success(`已生成 ${res.reversal_count} 张反冲单`);
  const calc = stalePeriodCalcTarget(row.id);
  await router.push({ path: calc.path, query: calc.query });
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
      const { excludeAttention, excludeAttentionAdjustments } = await promptExport({
        dateFrom: row.start_date,
        dateTo: row.end_date,
        periodId: row.id,
        siteId: row.site_id,
        title: `导出 ${row.start_date} ~ ${row.end_date}`,
      });
      await exportPeriodApi(row.id, {
        exclude_attention: excludeAttention,
        exclude_attention_adjustments: excludeAttentionAdjustments,
      });
      message.success(
        excludeAttention ? '已导出（已排除需关注订单）' : '已导出周期薪资',
      );
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

watch(onlyStale, () => {
  void gridApi.query();
});

watch(
  () => route.query.id,
  () => {
    void openPeriodByQueryId();
  },
);

onMounted(() => {
  const values: Record<string, unknown> = {};
  if (initialStatus && !lockDue) values.status = initialStatus;
  if (initialSiteId) values.site_id = initialSiteId;
  if (initialMonth) values.month = initialMonth;
  if (Object.keys(values).length) {
    void gridApi.formApi.setValues(values);
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
      data-testid="period-stale-scope"
      :data-month="initialMonth || undefined"
      :data-site-id="initialSiteId ? String(initialSiteId) : undefined"
      :message="staleHint"
      @close="onlyStale = false"
    />
    <a-alert
      v-if="missingPayrollHint"
      class="mb-2"
      show-icon
      type="warning"
      :message="missingPayrollHint"
    />
    <a-alert
      v-if="lockDueHint"
      class="mb-2"
      data-testid="period-lock-due-scope"
      show-icon
      type="info"
      :message="lockDueHint"
    />
    <a-alert
      v-else-if="periodScopeHint"
      class="mb-2"
      data-testid="period-list-scope"
      show-icon
      type="info"
      :message="periodScopeHint"
    />
    <a-alert
      v-if="lockFailText"
      class="mb-2"
      show-icon
      type="error"
      data-testid="period-lock-error"
      :message="lockFailText"
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
    <ExportConfirmModal />
  </PageContainer>
</template>
