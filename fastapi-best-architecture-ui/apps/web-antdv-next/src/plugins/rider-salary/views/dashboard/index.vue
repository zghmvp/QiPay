<script lang="ts" setup>
import type { DashboardSummary } from '../../types/dashboard';

import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { VbenButton } from '@vben/common-ui';

import { getDashboardSummaryApi } from '../../api/dashboard';
import SiteSelect from '../../components/SiteSelect.vue';
import { currentMonth } from '../../utils/date';
import PageContainer from '../_shared/PageContainer.vue';
import AttentionList from './components/AttentionList.vue';
import StatCards from './components/StatCards.vue';
import TopRiders from './components/TopRiders.vue';
import TrendChart from './components/TrendChart.vue';

const route = useRoute();
const router = useRouter();

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
    !trendVisible.value &&
    !topVisible.value
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
      </div>

      <!-- 模块级 skeleton：首屏加载 -->
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
          <AttentionList
            v-if="attentionVisible"
            :blocks="summary.attention ?? []"
            @refreshed="load"
          />
          <TrendChart v-if="trendVisible" :data="summary.trend ?? []" />
          <TopRiders
            v-if="topVisible"
            :bottom="summary.top_riders?.bottom ?? []"
            :top="summary.top_riders?.top ?? []"
          />
        </div>
      </template>
    </div>
  </PageContainer>
</template>
