<script lang="ts" setup>
import type { Dayjs } from 'dayjs';

import type {
  CalendarDayItem,
  CalendarPlanBand,
} from '../../../types/calendar';

import { computed } from 'vue';

import dayjs from 'dayjs';

import { buildMonthMatrix, WEEKDAY_LABELS } from '../../../utils/date';
import { slicesForWeek, splitPlanBandsByWeek } from '../bands';
import DayCell from './DayCell.vue';
import PlanBands from './PlanBands.vue';

const props = withDefaults(
  defineProps<{
    days?: CalendarDayItem[];
    month: string;
    planBands?: CalendarPlanBand[];
    selectedDate?: string;
  }>(),
  { days: () => [], planBands: () => [], selectedDate: undefined },
);

const emit = defineEmits<{
  bindPlan: [date: string];
  select: [date: string, inMonth: boolean];
}>();

const matrix = computed(() => buildMonthMatrix(props.month));
const todayKey = dayjs().format('YYYY-MM-DD');

const dayMap = computed(() => {
  const map = new Map<string, CalendarDayItem>();
  for (const item of props.days) {
    map.set(String(item.date).slice(0, 10), item);
  }
  return map;
});

const slices = computed(() =>
  splitPlanBandsByWeek(props.month, props.planBands),
);

function keyOf(day: Dayjs) {
  return day.format('YYYY-MM-DD');
}

function inMonth(day: Dayjs) {
  return day.format('YYYY-MM') === props.month;
}
</script>

<template>
  <div class="overflow-hidden rounded border">
    <div class="bg-muted grid grid-cols-7">
      <div
        v-for="label in WEEKDAY_LABELS"
        :key="label"
        class="px-2 py-2 text-center text-sm font-medium"
      >
        {{ label }}
      </div>
    </div>
    <div
      v-for="(week, wi) in matrix"
      :key="wi"
      class="relative grid grid-cols-7 border-t"
    >
      <PlanBands :slices="slicesForWeek(slices, wi)" />
      <DayCell
        v-for="day in week"
        :key="keyOf(day)"
        :date="keyOf(day)"
        :in-month="inMonth(day)"
        :item="inMonth(day) ? dayMap.get(keyOf(day)) : undefined"
        :selected="selectedDate === keyOf(day)"
        :today="keyOf(day) === todayKey"
        @bind-plan="emit('bindPlan', keyOf(day))"
        @click="emit('select', keyOf(day), inMonth(day))"
      />
    </div>
  </div>
</template>
