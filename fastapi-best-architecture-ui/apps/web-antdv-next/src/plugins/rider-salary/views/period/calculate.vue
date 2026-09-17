<script lang="ts" setup>
import type {
  CalcPrecheckBlocker,
  CalcPrecheckResult,
  CalcPrecheckWarning,
  CalculatePeriodResult,
  CalculateRiderFailure,
  PeriodWithPayrolls,
} from '../../types/period';
import type { PayrollSummary } from '../../types/payroll';
import type { RiderResult } from '../../types/rider';

import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { useAccess } from '@vben/access';
import { VbenButton } from '@vben/common-ui';

import { message } from 'antdv-next';

import {
  calcPrecheckApi,
  calculatePeriodApi,
  getPeriodApi,
} from '../../api/period';
import { getRiderListApi } from '../../api/rider';
import MoneyText from '../../components/MoneyText.vue';
import StatusTag from '../../components/StatusTag.vue';
import { PERIOD_STATUS_OPTIONS } from '../../constants/enums';
import PageContainer from '../_shared/PageContainer.vue';

const route = useRoute();
const router = useRouter();
const { hasAccessByCodes } = useAccess();

const canCalculate = computed(() =>
  hasAccessByCodes(['rs:period:calculate']),
);

const loading = ref(false);
const running = ref(false);
const period = ref<PeriodWithPayrolls>();
const precheck = ref<CalcPrecheckResult>();
const loadError = ref('');

const riderIds = ref<number[]>([]);
const riderOptions = ref<{ label: string; value: number }[]>([]);
const personal = ref(false);
const ridersLoading = ref(false);

const lastResult = ref<CalculatePeriodResult | null>(null);
const sessionFailed = ref<CalculateRiderFailure[]>([]);

const periodId = computed(() => Number(route.params.id));

const periodLocked = computed(() => {
  const status = period.value?.status;
  return status === 'locked' || status === 'paid';
});

const startDisabled = computed(() => {
  if (!canCalculate.value) return true;
  if (!precheck.value?.can_run) return true;
  if (periodLocked.value) return true;
  if (running.value) return true;
  return false;
});

function q(extra: Record<string, string | number | undefined>) {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(extra)) {
    if (v === undefined || v === null || v === '') continue;
    out[k] = String(v);
  }
  return out;
}

function parseRiderIdsQuery(): number[] {
  const raw = route.query.rider_ids;
  const text = Array.isArray(raw) ? raw[0] : raw;
  if (!text || typeof text !== 'string') return [];
  return text
    .split(',')
    .map((s) => Number(s.trim()))
    .filter((n) => Number.isFinite(n) && n > 0);
}

function pushDeeplink(
  path: string,
  query?: null | Record<string, string>,
) {
  router.push({ path, query: query ?? undefined });
}

function goBack() {
  router.push({
    path: '/rider-salary/period',
    query: q({ id: period.value?.id }),
  });
}

function goPeriodDetail() {
  router.push({
    path: '/rider-salary/period',
    query: q({ id: periodId.value }),
  });
}

function goPayrollList() {
  router.push({
    path: '/rider-salary/payroll',
    query: q({ period_id: periodId.value }),
  });
}

function goCalendar() {
  const p = period.value;
  if (!p) return;
  router.push({
    path: '/rider-salary/calendar',
    query: q({
      site_id: p.site_id,
      month: p.start_date?.slice(0, 7),
    }),
  });
}

function openPayroll(row: PayrollSummary) {
  router.push({ path: `/rider-salary/payroll/${row.id}` });
}

function blockerAction(row: CalcPrecheckBlocker) {
  if (row.deeplink?.path) {
    pushDeeplink(row.deeplink.path, row.deeplink.query);
    return;
  }
  if (row.code === 'no_plan_with_orders') {
    router.push({
      path: `/rider-salary/rider/${row.rider_id}`,
      query: { tab: 'binding' },
    });
    return;
  }
  const p = period.value;
  router.push({
    path: '/rider-salary/order',
    query: q({
      rider_id: row.rider_id,
      site_id: p?.site_id,
      date_from: p?.start_date,
      date_to: p?.end_date,
    }),
  });
}

function failureAction(row: CalculateRiderFailure, kind: 'binding' | 'order') {
  if (kind === 'binding') {
    router.push({
      path: `/rider-salary/rider/${row.rider_id}`,
      query: { tab: 'binding' },
    });
    return;
  }
  const p = period.value;
  router.push({
    path: '/rider-salary/order',
    query: q({
      rider_id: row.rider_id,
      site_id: p?.site_id,
      date_from: p?.start_date,
      date_to: p?.end_date,
    }),
  });
}

function failureLooksLikeNoPlan(row: CalculateRiderFailure) {
  return (row.errors ?? []).some((e) => e.includes('无生效方案'));
}

function warningAction(row: CalcPrecheckWarning) {
  if (row.deeplink?.path) {
    pushDeeplink(row.deeplink.path, row.deeplink.query);
  }
}

async function loadRiders(siteId: number, lockRiderId?: number) {
  ridersLoading.value = true;
  try {
    const res = await getRiderListApi({
      page: 1,
      site_id: siteId,
      size: 200,
    });
    riderOptions.value = (res?.items ?? []).map((item: RiderResult) => ({
      label: `${item.job_no} ${item.name}`,
      value: item.id,
    }));
    if (lockRiderId) {
      personal.value = true;
      riderIds.value = [lockRiderId];
    } else {
      personal.value = false;
      const preset = parseRiderIdsQuery();
      riderIds.value = preset.length ? preset : [];
    }
  } finally {
    ridersLoading.value = false;
  }
}

async function loadPage() {
  if (!Number.isFinite(periodId.value) || periodId.value <= 0) {
    loadError.value = '无效的周期 ID';
    return;
  }
  loading.value = true;
  loadError.value = '';
  try {
    const [periodRes, precheckRes] = await Promise.all([
      getPeriodApi(periodId.value),
      calcPrecheckApi(periodId.value),
    ]);
    period.value = periodRes;
    precheck.value = precheckRes;
    await loadRiders(
      periodRes.site_id,
      periodRes.rider_id ? periodRes.rider_id : undefined,
    );
  } catch (error: unknown) {
    loadError.value =
      (error as { message?: string })?.message || '加载周期算薪页失败';
  } finally {
    loading.value = false;
  }
}

async function onStartCalculate() {
  if (startDisabled.value || !period.value) return;
  running.value = true;
  lastResult.value = null;
  sessionFailed.value = [];
  try {
    const res = await calculatePeriodApi(period.value.id, {
      rider_ids: riderIds.value.length ? riderIds.value : null,
    });
    lastResult.value = res;
    sessionFailed.value = res.failed ?? [];
    const failedCount = sessionFailed.value.length;

    if (res.queued) {
      message.info('算薪已转入后台处理，请稍后刷新预检与结果');
    } else if (failedCount > 0 && res.calculated > 0) {
      message.info(`成功 ${res.calculated} 人，失败 ${failedCount} 人`);
    } else if (failedCount > 0) {
      message.error(`算薪失败 ${failedCount} 人，请查看失败清单`);
    } else {
      message.success(`已计算 ${res.calculated} 名骑手`);
    }

    // 刷新周期内已有薪资 + 预检
    const [periodRes, precheckRes] = await Promise.all([
      getPeriodApi(period.value.id),
      calcPrecheckApi(period.value.id),
    ]);
    period.value = periodRes;
    precheck.value = precheckRes;
  } finally {
    running.value = false;
  }
}

const payrollColumns = [
  { dataIndex: 'job_no', title: '工号', width: 100 },
  { dataIndex: 'rider_name', title: '姓名', width: 100 },
  { dataIndex: 'order_count', title: '单量', width: 70 },
  { dataIndex: 'gross', key: 'gross', title: '应发', width: 110 },
  { dataIndex: 'net', key: 'net', title: '实发', width: 110 },
  { dataIndex: 'stale', key: 'stale', title: '需重算', width: 80 },
  { dataIndex: 'action', key: 'action', title: '操作', width: 90 },
];

const blockerColumns = [
  { dataIndex: 'job_no', title: '工号', width: 100 },
  { dataIndex: 'rider_name', title: '姓名', width: 100 },
  { dataIndex: 'messages', key: 'messages', title: '问题' },
  { dataIndex: 'action', key: 'action', title: '操作', width: 140 },
];

const failedColumns = [
  { dataIndex: 'job_no', title: '工号', width: 100 },
  { dataIndex: 'rider_id', key: 'name', title: '骑手', width: 120 },
  { dataIndex: 'errors', key: 'errors', title: '错误' },
  { dataIndex: 'action', key: 'action', title: '操作', width: 180 },
];

watch(
  () => route.params.id,
  () => {
    lastResult.value = null;
    sessionFailed.value = [];
    void loadPage();
  },
);

onMounted(() => {
  void loadPage();
});
</script>

<template>
  <PageContainer>
    <a-spin :spinning="loading">
      <div class="mb-4 flex flex-wrap items-center gap-2">
        <VbenButton data-testid="period-calc-back" @click="goBack">
          ← 返回周期列表
        </VbenButton>
        <h2 class="m-0 text-lg font-medium" data-testid="period-calc-title">
          周期算薪
        </h2>
        <template v-if="period">
          <span class="text-muted-foreground">
            {{ period.site_name || period.site_code || '—' }} ·
            {{ period.start_date }} ~ {{ period.end_date }}
          </span>
          <StatusTag
            :options="PERIOD_STATUS_OPTIONS"
            :value="period.status"
          />
        </template>
      </div>

      <div v-if="period" class="mb-4 flex flex-wrap gap-2">
        <VbenButton size="small" @click="goPeriodDetail">打开周期详情</VbenButton>
        <VbenButton size="small" @click="goPayrollList">
          薪资结果(本周期)
        </VbenButton>
        <VbenButton size="small" @click="goCalendar">薪资日历</VbenButton>
      </div>

      <a-alert
        v-if="loadError"
        class="mb-4"
        type="error"
        show-icon
        :message="loadError"
      />

      <a-card
        v-if="period"
        class="mb-4"
        size="small"
        data-testid="period-calc-summary"
      >
        <a-descriptions :column="4" size="small">
          <a-descriptions-item label="骑手数">
            {{ period.rider_count ?? precheck?.eligible_rider_count ?? '—' }}
          </a-descriptions-item>
          <a-descriptions-item label="已有薪资单">
            {{ period.payroll_count ?? period.payrolls?.length ?? 0 }}
          </a-descriptions-item>
          <a-descriptions-item label="需重算">
            <span
              :class="
                (period.stale_count ?? 0) > 0 ? 'font-medium text-red-500' : ''
              "
            >
              {{ period.stale_count ?? precheck?.stale_count ?? 0 }}
            </span>
          </a-descriptions-item>
          <a-descriptions-item label="应发合计">
            <MoneyText :value="period.gross_total" />
          </a-descriptions-item>
        </a-descriptions>
      </a-card>

      <!-- ① 算前预检 -->
      <a-card
        class="mb-4"
        size="small"
        title="① 算前预检"
        data-testid="period-calc-precheck"
      >
        <a-alert
          v-if="!precheck?.can_run"
          class="mb-3"
          type="error"
          show-icon
          message="当前周期不可算薪（已锁账或已发薪）"
          data-testid="period-calc-blocker-period"
        />

        <a-alert
          v-for="(w, idx) in precheck?.warnings ?? []"
          :key="`w-${w.code}-${idx}`"
          class="mb-2"
          show-icon
          :type="w.code === 'period_not_open' ? 'error' : 'warning'"
          :message="w.messages.join('；')"
        >
          <template v-if="w.deeplink" #action>
            <VbenButton size="small" @click="warningAction(w)">去查看</VbenButton>
          </template>
        </a-alert>

        <div
          v-if="precheck?.blockers?.length"
          class="mb-3"
          data-testid="period-calc-blockers"
        >
          <div class="mb-2 font-medium text-red-600">
            骑手硬风险（{{ precheck.blockers.length }}）— 不阻止整页开算，失败将进入结果区
          </div>
          <a-table
            size="small"
            :pagination="false"
            :columns="blockerColumns"
            :data-source="precheck.blockers"
            row-key="rider_id"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'messages'">
                <div
                  v-for="(m, i) in (record as CalcPrecheckBlocker).messages"
                  :key="i"
                >
                  {{ m }}
                </div>
              </template>
              <template v-else-if="column.key === 'action'">
                <VbenButton
                  size="small"
                  type="link"
                  data-testid="period-calc-blocker-fix"
                  @click="blockerAction(record as CalcPrecheckBlocker)"
                >
                  {{
                    (record as CalcPrecheckBlocker).code === 'no_plan_with_orders'
                      ? '去绑定'
                      : '看订单'
                  }}
                </VbenButton>
              </template>
            </template>
          </a-table>
        </div>

        <a-alert
          v-else-if="precheck?.can_run"
          class="mb-3"
          type="success"
          show-icon
          message="未发现骑手级硬风险（仍以正式算薪结果为准）"
        />

        <div class="mb-2 text-sm text-muted-foreground">
          不选骑手则计算周期内全部骑手。个性化周期骑手不会写入站点级结果。
        </div>
        <div class="flex flex-wrap items-start gap-3">
          <a-select
            v-model:value="riderIds"
            allow-clear
            class="min-w-[280px] flex-1"
            mode="multiple"
            placeholder="默认全部骑手"
            :disabled="personal"
            :loading="ridersLoading"
            :options="riderOptions"
            option-filter-prop="label"
            show-search
            data-testid="period-calc-riders"
          />
          <VbenButton
            v-if="canCalculate"
            type="primary"
            :disabled="startDisabled"
            :loading="running"
            data-testid="period-calc-start"
            @click="onStartCalculate"
          >
            开始算薪
          </VbenButton>
          <a-tooltip v-else title="无算薪权限，可只读查看预检与已有结果">
            <VbenButton disabled data-testid="period-calc-start-disabled">
              开始算薪
            </VbenButton>
          </a-tooltip>
        </div>
      </a-card>

      <!-- ② 本次结果 -->
      <a-card
        class="mb-4"
        size="small"
        title="② 本次结果"
        data-testid="period-calc-result"
      >
        <template v-if="lastResult">
          <a-alert
            class="mb-3"
            show-icon
            :type="
              lastResult.queued
                ? 'info'
                : (lastResult.failed?.length ?? 0) > 0
                  ? 'warning'
                  : 'success'
            "
            :message="
              lastResult.queued
                ? '已转入后台处理'
                : `成功 ${lastResult.calculated} · 失败 ${lastResult.failed?.length ?? 0}`
            "
          />

          <div
            v-if="sessionFailed.length"
            class="mb-4"
            data-testid="period-calc-failed"
          >
            <div class="mb-2 font-medium text-red-600">失败清单（主）</div>
            <a-table
              size="small"
              :pagination="false"
              :columns="failedColumns"
              :data-source="sessionFailed"
              :row-key="(r: CalculateRiderFailure) => r.rider_id"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'name'">
                  {{
                    (record as CalculateRiderFailure).job_no
                      ? `工号 ${(record as CalculateRiderFailure).job_no}`
                      : `骑手 #${(record as CalculateRiderFailure).rider_id}`
                  }}
                </template>
                <template v-else-if="column.key === 'errors'">
                  <div
                    v-for="(e, i) in (record as CalculateRiderFailure).errors"
                    :key="i"
                  >
                    {{ e }}
                  </div>
                </template>
                <template v-else-if="column.key === 'action'">
                  <VbenButton
                    v-if="failureLooksLikeNoPlan(record as CalculateRiderFailure)"
                    size="small"
                    type="link"
                    data-testid="period-calc-fail-binding"
                    @click="
                      failureAction(record as CalculateRiderFailure, 'binding')
                    "
                  >
                    去绑定
                  </VbenButton>
                  <VbenButton
                    size="small"
                    type="link"
                    data-testid="period-calc-fail-order"
                    @click="
                      failureAction(record as CalculateRiderFailure, 'order')
                    "
                  >
                    看订单
                  </VbenButton>
                </template>
              </template>
            </a-table>
          </div>
          <a-empty
            v-else-if="!lastResult.queued"
            description="无失败骑手"
            class="mb-2"
          />
        </template>
        <a-empty v-else description="尚未开算；点「开始算薪」后在此展示本次结果" />
      </a-card>

      <!-- ③ 已有薪资 -->
      <a-card
        size="small"
        title="③ 周期内已有薪资"
        data-testid="period-calc-payrolls"
      >
        <a-table
          size="small"
          :pagination="false"
          :columns="payrollColumns"
          :data-source="period?.payrolls ?? []"
          row-key="id"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'gross'">
              <MoneyText :value="(record as PayrollSummary).gross" />
            </template>
            <template v-else-if="column.key === 'net'">
              <MoneyText :value="(record as PayrollSummary).net" />
            </template>
            <template v-else-if="column.key === 'stale'">
              {{ (record as PayrollSummary).stale ? '是' : '否' }}
            </template>
            <template v-else-if="column.key === 'action'">
              <VbenButton
                size="small"
                type="link"
                data-testid="period-calc-payroll-detail"
                @click="openPayroll(record as PayrollSummary)"
              >
                明细
              </VbenButton>
            </template>
          </template>
        </a-table>
      </a-card>
    </a-spin>
  </PageContainer>
</template>
