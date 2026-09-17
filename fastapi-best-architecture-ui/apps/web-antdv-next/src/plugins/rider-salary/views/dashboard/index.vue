<script lang="ts" setup>
import type { DashboardSummary, RecalcJobDetail } from '../../types/dashboard';

import { computed, onUnmounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { useAccess } from '@vben/access';
import { VbenButton, confirm } from '@vben/common-ui';

import { message } from 'antdv-next';

import {
  getDashboardSummaryApi,
  getRecalcJobApi,
  previewStaleBatchRecalcApi,
  submitStaleBatchRecalcApi,
} from '../../api/dashboard';
import SiteSelect from '../../components/SiteSelect.vue';
import { currentMonth } from '../../utils/date';
import PageContainer from '../_shared/PageContainer.vue';
import AttentionList from './components/AttentionList.vue';
import StatCards from './components/StatCards.vue';
import TopRiders from './components/TopRiders.vue';
import TrendChart from './components/TrendChart.vue';

const route = useRoute();
const router = useRouter();
const { hasAccessByCodes } = useAccess();

function queryNum(key: string) {
  const raw = route.query[key];
  const n = Number(Array.isArray(raw) ? raw[0] : raw);
  return Number.isFinite(n) && n > 0 ? n : undefined;
}

function queryStr(key: string) {
  const raw = route.query[key];
  const v = Array.isArray(raw) ? raw[0] : raw;
  return typeof v === 'string' && v ? v : undefined;
}

const siteId = ref<null | number | undefined>(queryNum('site_id') ?? null);
const month = ref(queryStr('month') || currentMonth());
const loading = ref(false);
const failed = ref(false);
const summary = ref<DashboardSummary>();
const batchRecalcing = ref(false);
const batchJob = ref<RecalcJobDetail>();
let batchPollTimer: null | ReturnType<typeof setInterval> = null;

const batchFailed = computed(() => {
  const job = batchJob.value;
  if (!job) return false;
  return (
    job.status === 'failed' ||
    (job.failed_rider_count ?? job.payload?.failed_rider_count ?? 0) > 0
  );
});

const batchFailedPeriodIds = computed(() => {
  const payload = batchJob.value?.payload;
  const ids = payload?.failed_period_ids ?? [];
  const extra = (payload?.failed ?? [])
    .map((row) => Number(row.period_id))
    .filter((n) => Number.isFinite(n) && n > 0);
  return [...new Set([...ids.map(Number), ...extra].filter((n) => n > 0))];
});

function stopBatchPoll() {
  if (batchPollTimer) {
    clearInterval(batchPollTimer);
    batchPollTimer = null;
  }
}

async function refreshBatchJob(jobId: number) {
  const job = await getRecalcJobApi(jobId);
  batchJob.value = job;
  if (job.status === 'done' || job.status === 'failed') {
    stopBatchPoll();
    if (batchFailed.value) {
      message.error(job.message || '批量重算部分失败，请到算薪页查看失败清单');
    } else {
      message.info(job.message || '批量重算已结束');
    }
    await load();
  }
  return job;
}

function startBatchPoll(jobId: number) {
  stopBatchPoll();
  void refreshBatchJob(jobId);
  batchPollTimer = setInterval(() => {
    void refreshBatchJob(jobId).catch(() => stopBatchPoll());
  }, 1500);
}

function goCalcPage(periodId: number) {
  void router.push({ path: `/rider-salary/period/${periodId}/calculate` });
}

const canCalculate = computed(() =>
  hasAccessByCodes(['rs:period:calculate']),
);

const staleCount = computed(() => {
  const block = summary.value?.attention?.find((b) => b.key === 'stale_periods');
  return block?.count ?? 0;
});

const trendVisible = computed(() => {
  const points = summary.value?.trend ?? [];
  return points.some(
    (item) => item.order_count > 0 || Number(item.formula_amount ?? 0) !== 0,
  );
});

const topVisible = computed(() => {
  const top = summary.value?.top_riders;
  return Boolean(top?.top?.length || top?.bottom?.length);
});

const attentionVisible = computed(() =>
  (summary.value?.attention ?? []).some((item) => item.count > 0),
);

const insightVisible = computed(() => trendVisible.value || topVisible.value);

/** 洞察默认折叠，突出待办主轴 */
const insightKeys = ref<string[]>([]);

const pageEmpty = computed(() => {
  const data = summary.value;
  if (!data) return !failed.value && !loading.value;
  const cards = data.cards;
  const cardsZero =
    !cards.on_job_riders &&
    !cards.month_order_count &&
    !cards.month_valid_order_count &&
    !cards.pending_advances &&
    !cards.to_pay_advances &&
    Number(cards.estimated_gross ?? 0) === 0;
  return (
    cardsZero &&
    !attentionVisible.value &&
    !insightVisible.value
  );
});

function syncQuery() {
  router.replace({
    query: {
      ...(siteId.value ? { site_id: String(siteId.value) } : {}),
      month: month.value,
    },
  });
}

async function load() {
  loading.value = true;
  failed.value = false;
  try {
    summary.value = await getDashboardSummaryApi({
      month: month.value,
      site_id: siteId.value ?? undefined,
    });
  } catch {
    summary.value = undefined;
    failed.value = true;
  } finally {
    loading.value = false;
  }
}

async function onBatchRecalcStale() {
  if (!siteId.value) {
    message.warning('请先选择单个站点后再批量重算');
    return;
  }
  let preview;
  try {
    preview = await previewStaleBatchRecalcApi({
      month: month.value,
      site_id: siteId.value,
    });
  } catch {
    return;
  }
  if (!preview.period_count) {
    message.info('本站本月暂无需要重算的周期');
    return;
  }
  try {
    await confirm({
      content: `确认对站点「${preview.site_name}」${preview.month} 批量重算？涉及 ${preview.period_count} 个周期、${preview.stale_rider_count} 名骑手需重算。取消则数据不变。`,
      icon: 'warning',
    });
  } catch {
    return;
  }
  batchRecalcing.value = true;
  try {
    const res = await submitStaleBatchRecalcApi({
      month: month.value,
      site_id: siteId.value,
    });
    message.info(res.message || '已提交批量重算');
    if (res.job_id) {
      startBatchPoll(res.job_id);
    }
    await load();
  } finally {
    batchRecalcing.value = false;
  }
}

onUnmounted(stopBatchPoll);

watch([siteId, month], () => {
  syncQuery();
  load();
});

load();
</script>

<template>
  <PageContainer>
    <div class="flex min-h-0 flex-1 flex-col overflow-auto">
      <div class="mb-4 flex flex-wrap items-center gap-3">
        <SiteSelect v-model:value="siteId" allow-all />
        <a-date-picker
          v-model:value="month"
          picker="month"
          value-format="YYYY-MM"
        />
        <VbenButton variant="outline" @click="load">刷新</VbenButton>
        <VbenButton
          v-if="canCalculate"
          :disabled="!siteId || staleCount === 0"
          :loading="batchRecalcing"
          data-testid="stale-batch-recalc"
          @click="onBatchRecalcStale"
        >
          本站本月批量重算
        </VbenButton>
      </div>

      <div v-if="loading && !summary" class="flex flex-col gap-4">
        <a-skeleton active :paragraph="{ rows: 2 }" />
        <a-card size="small">
          <a-skeleton active :paragraph="{ rows: 4 }" />
        </a-card>
        <a-card size="small">
          <a-skeleton active :paragraph="{ rows: 3 }" />
        </a-card>
      </div>

      <template v-else>
        <a-empty v-if="failed" description="工作台加载失败，请重试">
          <VbenButton class="mt-2" @click="load">重试</VbenButton>
        </a-empty>
        <a-empty
          v-else-if="pageEmpty"
          description="本月暂无需要处理的事项，请先导入订单明细"
        >
          <VbenButton
            class="mt-2"
            @click="router.push('/rider-salary/order')"
          >
            去导入订单
          </VbenButton>
        </a-empty>
        <div v-else-if="summary" class="relative flex flex-col gap-4">
          <div
            v-if="loading"
            class="bg-background/60 absolute inset-0 z-10 flex items-start justify-center pt-8"
          >
            <a-spin />
          </div>
          <StatCards :cards="summary.cards" />
          <div
            v-if="batchJob"
            class="mb-2"
            data-testid="dashboard-batch-job"
          >
            <a-alert
              v-if="batchJob.status === 'queued' || batchJob.status === 'running'"
              show-icon
              type="info"
              :message="`批量重算：${batchJob.status_label || batchJob.status}`"
              :description="batchJob.message || '完成后请核对算薪页，勿当作已出账'"
            />
            <a-alert
              v-else-if="batchFailed"
              show-icon
              type="error"
              data-testid="dashboard-batch-failed"
              :message="batchJob.message?.includes('部分失败') ? '批量重算部分失败' : '批量重算失败'"
              :description="batchJob.message || '请到算薪页查看失败清单'"
            />
            <a-alert
              v-else
              show-icon
              type="info"
              :message="batchJob.message || '批量重算已结束'"
            />
            <div
              v-if="batchFailed && batchFailedPeriodIds.length"
              class="mt-2 flex flex-wrap gap-2"
            >
              <a-button
                v-for="pid in batchFailedPeriodIds"
                :key="pid"
                size="small"
                data-testid="dashboard-batch-goto-calc"
                @click="goCalcPage(pid)"
              >
                去算薪页 #{{ pid }}
              </a-button>
            </div>
          </div>
          <AttentionList
            v-if="attentionVisible"
            :blocks="summary.attention ?? []"
            data-testid="dashboard-attention"
          />
          <a-collapse
            v-if="insightVisible"
            v-model:active-key="insightKeys"
            :bordered="false"
            class="bg-transparent"
          >
            <a-collapse-panel key="insight" header="洞察（趋势 / Top 骑手）">
              <div class="flex flex-col gap-4">
                <TrendChart v-if="trendVisible" :data="summary.trend ?? []" />
                <TopRiders
                  v-if="topVisible"
                  :bottom="summary.top_riders?.bottom ?? []"
                  :top="summary.top_riders?.top ?? []"
                />
              </div>
            </a-collapse-panel>
          </a-collapse>
        </div>
      </template>
    </div>
  </PageContainer>
</template>
