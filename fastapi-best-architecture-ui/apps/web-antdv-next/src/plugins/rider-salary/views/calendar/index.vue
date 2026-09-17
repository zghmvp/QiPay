<script lang="ts" setup>
import type { CalendarMonth } from '../../types/calendar';
import type { RiderResult } from '../../types/rider';

import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { VbenButton } from '@vben/common-ui';
import { IconifyIcon } from '@vben/icons';

import { message } from 'antdv-next';
import dayjs from 'dayjs';

import { getCalendarMonthApi } from '../../api/calendar';
import { exportPeriodApi } from '../../api/period';
import { getRiderApi } from '../../api/rider';
import RiderSelect from '../../components/RiderSelect.vue';
import SalaryCalendar from '../../components/SalaryCalendar.vue';
import SiteSelect from '../../components/SiteSelect.vue';
import { currentMonth } from '../../utils/date';
import PageContainer from '../_shared/PageContainer.vue';
import { useExportConfirm } from '../period/components/use-export-confirm';
import DayDrawer from './components/DayDrawer.vue';
import SummaryBar from './components/SummaryBar.vue';

const route = useRoute();
const router = useRouter();
const { ExportConfirmModal, prompt: promptExport } = useExportConfirm();

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

const siteId = ref<number | undefined>(queryNum('site_id'));
const riderId = ref<number | undefined>(queryNum('rider_id'));
const month = ref(queryStr('month') || currentMonth());
const selectedDate = ref<string | undefined>(queryStr('date'));
const drawerOpen = ref(Boolean(queryStr('date')));
const riderName = ref('');
const loading = ref(false);
const failed = ref(false);
const data = ref<CalendarMonth>();
const exporting = ref(false);

const emptyHint = computed(() => {
  if (!siteId.value || !riderId.value) return '请选择站点和骑手';
  return '';
});

function syncQuery() {
  router.replace({
    query: {
      ...(siteId.value ? { site_id: String(siteId.value) } : {}),
      ...(riderId.value ? { rider_id: String(riderId.value) } : {}),
      month: month.value,
      ...(selectedDate.value && drawerOpen.value
        ? { date: selectedDate.value }
        : {}),
    },
  });
}

async function loadRiderName(id?: number) {
  if (!id) {
    riderName.value = '';
    return;
  }
  try {
    const row = await getRiderApi(id);
    riderName.value = row?.name ?? '';
    if (!siteId.value && row?.site_id) siteId.value = row.site_id;
  } catch {
    riderName.value = '';
  }
}

async function load() {
  if (!riderId.value) {
    data.value = undefined;
    return;
  }
  loading.value = true;
  failed.value = false;
  try {
    data.value = await getCalendarMonthApi(riderId.value, month.value);
  } catch {
    data.value = undefined;
    failed.value = true;
  } finally {
    loading.value = false;
  }
}

function shiftMonth(delta: number) {
  month.value = dayjs(`${month.value}-01`)
    .add(delta, 'month')
    .format('YYYY-MM');
  closeDrawer();
}

function closeDrawer() {
  drawerOpen.value = false;
  selectedDate.value = undefined;
}

function onSelect(date: string, inMonth: boolean) {
  if (!inMonth) {
    month.value = date.slice(0, 7);
    selectedDate.value = date;
    drawerOpen.value = true;
    return;
  }
  selectedDate.value = date;
  drawerOpen.value = true;
}

function goBindingFromCell(_date: string) {
  if (!riderId.value) {
    message.warning('请先选择骑手');
    return;
  }
  void router.push({
    path: `/rider-salary/rider/${riderId.value}`,
    query: { tab: 'binding' },
  });
}

function onShiftDate(date: string) {
  selectedDate.value = date;
  drawerOpen.value = true;
  const nextMonth = date.slice(0, 7);
  if (nextMonth !== month.value) month.value = nextMonth;
}

function onRiderChange(_id: null | number | undefined, row?: RiderResult) {
  riderName.value = row?.name ?? '';
}

async function exportMonth() {
  const periods = data.value?.summary.periods ?? [];
  if (!periods.length) {
    message.warning('本月暂无结算周期，无法导出');
    return;
  }
  if (!siteId.value) {
    message.warning('请先选择站点');
    return;
  }
  const dateFrom = `${month.value}-01`;
  const dateTo = dayjs(`${month.value}-01`).endOf('month').format('YYYY-MM-DD');
  try {
    const { excludeAttention } = await promptExport({
      dateFrom,
      dateTo,
      siteId: siteId.value,
      title: `导出 ${month.value} 明细`,
    });
    exporting.value = true;
    try {
      for (const period of periods) {
        await exportPeriodApi(period.id, { exclude_attention: excludeAttention });
      }
      message.success(
        periods.length > 1 ? `已导出 ${periods.length} 个周期明细` : '已导出当月明细',
      );
    } finally {
      exporting.value = false;
    }
  } catch (error: unknown) {
    const msg = (error as Error)?.message;
    if (msg === 'cancelled' || msg === 'dialog cancelled') return;
    throw error;
  }
}

function onKey(e: KeyboardEvent) {
  if (!drawerOpen.value || !selectedDate.value) return;
  if (e.key === 'Escape') {
    closeDrawer();
    return;
  }
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    e.preventDefault();
    onShiftDate(
      dayjs(selectedDate.value)
        .add(e.key === 'ArrowRight' ? 1 : -1, 'day')
        .format('YYYY-MM-DD'),
    );
  }
}

watch([siteId, riderId, month, selectedDate, drawerOpen], syncQuery);
watch(month, () => {
  if (
    selectedDate.value &&
    selectedDate.value.slice(0, 7) === month.value &&
    drawerOpen.value
  ) {
    return;
  }
  closeDrawer();
});
watch(riderId, (id) => {
  loadRiderName(id);
  closeDrawer();
});
watch([riderId, month], load);

onMounted(() => {
  window.addEventListener('keydown', onKey);
  if (riderId.value) loadRiderName(riderId.value);
  load();
});
onUnmounted(() => window.removeEventListener('keydown', onKey));
</script>

<template>
  <PageContainer>
    <div class="flex min-h-0 flex-1 flex-col overflow-auto">
    <div class="mb-4 flex flex-wrap items-center gap-3">
      <SiteSelect v-model:value="siteId" />
      <RiderSelect
        v-model:value="riderId"
        :site-id="siteId"
        @change="onRiderChange"
      />
      <div class="flex items-center gap-1">
        <VbenButton size="sm" variant="outline" @click="shiftMonth(-1)">
          ‹
        </VbenButton>
        <a-date-picker
          v-model:value="month"
          picker="month"
          value-format="YYYY-MM"
        />
        <VbenButton size="sm" variant="outline" @click="shiftMonth(1)">
          ›
        </VbenButton>
      </div>
      <div class="ml-auto flex items-center gap-2">
        <VbenButton
          v-access:code="'rs:period:export'"
          :disabled="!riderId"
          :loading="exporting"
          variant="outline"
          @click="exportMonth"
        >
          <IconifyIcon class="mr-1 size-4" icon="lucide:download" />
          导出当月明细
        </VbenButton>
        <VbenButton :disabled="!riderId" variant="outline" @click="load">
          刷新
        </VbenButton>
      </div>
    </div>

    <a-empty v-if="emptyHint" :description="emptyHint" />
    <a-empty v-else-if="failed" description="日历加载失败，请重试">
      <VbenButton class="mt-2" @click="load">重试</VbenButton>
    </a-empty>
    <a-spin v-else :spinning="loading">
      <div class="flex flex-col gap-4">
        <SummaryBar :summary="data?.summary" />
        <SalaryCalendar
          :days="data?.days ?? []"
          :month="month"
          :plan-bands="data?.plan_bands ?? []"
          :selected-date="selectedDate"
          @bind-plan="goBindingFromCell"
          @select="onSelect"
        />
      </div>
    </a-spin>
    </div>

    <DayDrawer
      v-model:open="drawerOpen"
      :date="selectedDate"
      :rider-id="riderId"
      :rider-name="riderName"
      :site-id="siteId"
      @shift-date="onShiftDate"
    />
    <ExportConfirmModal />
  </PageContainer>
</template>
