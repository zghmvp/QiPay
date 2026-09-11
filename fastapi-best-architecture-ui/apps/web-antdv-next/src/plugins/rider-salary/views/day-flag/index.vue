<script lang="ts" setup>
import type { Dayjs } from 'dayjs';

import type { DayFlagItem, DayFlagResult } from '../../types/day-flag';

import { computed, reactive, ref, watch } from 'vue';

import { VbenButton } from '@vben/common-ui';
import { IconifyIcon } from '@vben/icons';

import { message } from 'antdv-next';
import dayjs from 'dayjs';

import { getDayFlagsApi, upsertDayFlagsApi } from '../../api/day-flag';
import SiteSelect from '../../components/SiteSelect.vue';
import {
  buildMonthMatrix,
  currentMonth,
  WEEKDAY_LABELS,
} from '../../utils/date';
import PageContainer from '../_shared/PageContainer.vue';
import DayCell from './components/DayCell.vue';

interface CellState {
  bad_weather: boolean;
  high_temp: boolean;
  locked: boolean;
  promo: boolean;
  remark: string;
}

const siteId = ref<number>();
const month = ref(currentMonth());
const loading = ref(false);
const saving = ref(false);
const cells = reactive<Record<string, CellState>>({});

const matrix = computed(() => buildMonthMatrix(month.value));
const monthStart = computed(() => dayjs(`${month.value}-01`));

function emptyCell(): CellState {
  return {
    bad_weather: false,
    high_temp: false,
    locked: false,
    promo: false,
    remark: '',
  };
}

function fillMonthKeys() {
  const start = dayjs(`${month.value}-01`);
  const end = start.endOf('month');
  let cursor = start;
  while (cursor.isBefore(end) || cursor.isSame(end, 'day')) {
    const key = cursor.format('YYYY-MM-DD');
    if (!cells[key]) cells[key] = emptyCell();
    cursor = cursor.add(1, 'day');
  }
}

function keyOf(day: Dayjs) {
  return day.format('YYYY-MM-DD');
}

function isCurrentMonth(day: Dayjs) {
  return day.format('YYYY-MM') === month.value;
}

async function load() {
  if (!siteId.value) return;
  loading.value = true;
  try {
    const list = (await getDayFlagsApi({
      month: month.value,
      site_id: siteId.value,
    })) as DayFlagResult[];
    Object.keys(cells).forEach((key) => delete cells[key]);
    fillMonthKeys();
    for (const item of list ?? []) {
      const key = String(item.biz_date).slice(0, 10);
      cells[key] = {
        bad_weather: Boolean(item.bad_weather),
        high_temp: Boolean(item.high_temp),
        locked: false,
        promo: Boolean(item.promo),
        remark: item.remark || '',
      };
    }
  } finally {
    loading.value = false;
  }
}

watch([siteId, month], () => {
  if (siteId.value) load();
});

async function save() {
  if (!siteId.value) {
    message.warning('请先选择站点');
    return;
  }
  const days: DayFlagItem[] = [];
  const start = monthStart.value;
  const end = start.endOf('month');
  let cursor = start;
  while (cursor.isBefore(end) || cursor.isSame(end, 'day')) {
    const state = cells[cursor.format('YYYY-MM-DD')] ?? emptyCell();
    if (!state.locked) {
      days.push({
        bad_weather: state.bad_weather,
        biz_date: cursor.format('YYYY-MM-DD'),
        high_temp: state.high_temp,
        promo: state.promo,
        remark: state.remark || null,
      });
    }
    cursor = cursor.add(1, 'day');
  }
  saving.value = true;
  try {
    await upsertDayFlagsApi({ days, site_id: siteId.value });
    message.success('已保存日标记，已标记相关薪资需重算');
    await load();
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <PageContainer>
    <div class="flex min-h-0 flex-1 flex-col overflow-auto">
    <div class="mb-4 flex flex-wrap items-center gap-3">
      <SiteSelect v-model:value="siteId" />
      <a-date-picker
        v-model:value="month"
        picker="month"
        value-format="YYYY-MM"
      />
      <VbenButton
        v-access:code="'rs:dayflag:edit'"
        :disabled="!siteId"
        :loading="saving"
        @click="save"
      >
        保存本月
      </VbenButton>
    </div>
    <a-empty
      v-if="!siteId"
      description="请选择站点后编辑日标记"
    />
    <a-spin v-else :spinning="loading">
      <div class="grid grid-cols-7 gap-px overflow-hidden rounded border bg-border">
        <div
          v-for="label in WEEKDAY_LABELS"
          :key="label"
          class="bg-muted px-2 py-2 text-center text-sm font-medium"
        >
          {{ label }}
        </div>
        <template v-for="(week, wi) in matrix" :key="wi">
          <div
            v-for="day in week"
            :key="keyOf(day)"
            class="min-h-[110px] bg-background p-2"
            :class="isCurrentMonth(day) ? '' : 'opacity-40'"
          >
            <div class="mb-1 flex items-center justify-between">
              <span class="text-sm">{{ day.date() }}</span>
              <a-tooltip v-if="cells[keyOf(day)]?.locked" title="该日期所属结算周期已锁账，禁止修改">
                <IconifyIcon class="size-3.5 text-red-500" icon="lucide:lock" />
              </a-tooltip>
            </div>
            <DayCell
              v-if="isCurrentMonth(day) && cells[keyOf(day)]"
              :cell="cells[keyOf(day)] ?? emptyCell()"
              @update:cell="(v) => (cells[keyOf(day)] = v)"
            />
          </div>
        </template>
      </div>
    </a-spin>
    </div>
  </PageContainer>
</template>
