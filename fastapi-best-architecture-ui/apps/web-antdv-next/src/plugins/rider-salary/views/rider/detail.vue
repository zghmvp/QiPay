<script lang="ts" setup>
import type { CalendarMonth } from '../../types/calendar';
import type { RiderResult } from '../../types/rider';

import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { VbenButton } from '@vben/common-ui';

import dayjs from 'dayjs';

import { getCalendarMonthApi } from '../../api/calendar';
import { getRiderApi } from '../../api/rider';
import SalaryCalendar from '../../components/SalaryCalendar.vue';
import StatusTag from '../../components/StatusTag.vue';
import {
  EMPLOY_TYPE_OPTIONS,
  RIDER_STATUS_OPTIONS,
} from '../../constants/enums';
import { currentMonth } from '../../utils/date';
import PageContainer from '../_shared/PageContainer.vue';
import BindingPanel from './components/BindingPanel.vue';
import EmployPanel from './components/EmployPanel.vue';

const route = useRoute();
const router = useRouter();

const riderId = computed(() => Number(route.params.id));
const activeTab = ref('overview');
const rider = ref<RiderResult>();
const loading = ref(false);
const calendarLoading = ref(false);
const month = ref(currentMonth());
const calendar = ref<CalendarMonth>();

const title = computed(() =>
  rider.value ? `${rider.value.name}（${rider.value.job_no}）` : '骑手档案',
);

async function loadRider() {
  if (!Number.isFinite(riderId.value)) return;
  loading.value = true;
  try {
    rider.value = await getRiderApi(riderId.value);
  } finally {
    loading.value = false;
  }
}

async function loadCalendar() {
  if (!riderId.value) return;
  calendarLoading.value = true;
  try {
    calendar.value = await getCalendarMonthApi(riderId.value, month.value);
  } catch {
    calendar.value = undefined;
  } finally {
    calendarLoading.value = false;
  }
}

function shiftMonth(delta: number) {
  month.value = dayjs(`${month.value}-01`).add(delta, 'month').format('YYYY-MM');
}

function goFullCalendar() {
  if (!rider.value) return;
  router.push({
    path: '/rider-salary/calendar',
    query: {
      month: month.value,
      rider_id: String(rider.value.id),
      site_id: String(rider.value.site_id),
    },
  });
}

function onChildChanged() {
  void loadRider();
  if (activeTab.value === 'overview') void loadCalendar();
}

watch(activeTab, (tab) => {
  router.replace({
    query: { ...route.query, tab },
  });
  if (tab === 'overview') void loadCalendar();
});

watch(month, () => {
  if (activeTab.value === 'overview') void loadCalendar();
});

watch(riderId, () => {
  void loadRider();
  void loadCalendar();
});

onMounted(async () => {
  const tab = route.query.tab;
  if (typeof tab === 'string' && ['binding', 'employ', 'overview'].includes(tab)) {
    activeTab.value = tab;
  }
  await loadRider();
  if (activeTab.value === 'overview') await loadCalendar();
});
</script>

<template>
  <PageContainer>
    <a-spin :spinning="loading">
      <div class="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div class="flex items-center gap-2">
            <a-button type="link" class="px-0" @click="router.push('/rider-salary/rider')">
              ← 返回列表
            </a-button>
          </div>
          <h2 class="text-xl font-semibold">{{ title }}</h2>
          <div v-if="rider" class="text-muted-foreground mt-1 flex flex-wrap items-center gap-2 text-sm">
            <span>{{ rider.site_name || '—' }}</span>
            <StatusTag :options="RIDER_STATUS_OPTIONS" :value="rider.status" />
            <StatusTag :options="EMPLOY_TYPE_OPTIONS" :value="rider.employ_type" />
            <span>
              当前方案：
              <span v-if="rider.plan_short_name" class="inline-flex items-center gap-1">
                <span
                  class="inline-block size-2 rounded-full"
                  :style="{ background: rider.plan_color || '#1677ff' }"
                ></span>
                {{ rider.plan_short_name }}
              </span>
              <span v-else>未绑定</span>
            </span>
            <span>入职 {{ rider.hire_date }}</span>
          </div>
        </div>
        <div class="flex flex-wrap gap-2">
          <VbenButton variant="outline" @click="goFullCalendar">打开完整薪资日历</VbenButton>
          <VbenButton
            v-access:code="'rs:rider:edit'"
            variant="outline"
            @click="router.push({ path: '/rider-salary/rider', query: { edit_id: String(riderId) } })"
          >
            编辑基本信息
          </VbenButton>
        </div>
      </div>

      <a-tabs v-model:active-key="activeTab">
        <a-tab-pane key="overview" tab="薪资概览">
          <div v-if="rider" class="flex flex-col gap-4">
            <a-alert type="info" show-icon>
              <template #message>日历与方案绑定联动</template>
              <template #description>
                彩色条带表示该骑手在各日期的生效方案；切换方案请切到「方案绑定」页签，保存后需重新试算相关周期。
              </template>
            </a-alert>
            <div class="flex items-center gap-2">
              <VbenButton size="sm" variant="outline" @click="shiftMonth(-1)">‹</VbenButton>
              <a-date-picker v-model:value="month" picker="month" value-format="YYYY-MM" />
              <VbenButton size="sm" variant="outline" @click="shiftMonth(1)">›</VbenButton>
            </div>
            <a-spin :spinning="calendarLoading">
              <SalaryCalendar
                :days="calendar?.days ?? []"
                :month="month"
                :plan-bands="calendar?.plan_bands ?? []"
              />
            </a-spin>
          </div>
        </a-tab-pane>

        <a-tab-pane key="binding" tab="方案绑定">
          <BindingPanel v-if="rider" :rider="rider" @changed="onChildChanged" />
        </a-tab-pane>

        <a-tab-pane key="employ" tab="用工类型">
          <EmployPanel v-if="rider" :rider="rider" @changed="onChildChanged" />
        </a-tab-pane>
      </a-tabs>
    </a-spin>
  </PageContainer>
</template>
