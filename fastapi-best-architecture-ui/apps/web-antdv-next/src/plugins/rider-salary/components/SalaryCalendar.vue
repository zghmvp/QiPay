<script lang="ts" setup>
import type {
  CalendarDayItem,
  CalendarPlanBand,
} from '../types/calendar';

import MonthGrid from '../views/calendar/components/MonthGrid.vue';

const props = withDefaults(
  defineProps<{
    days?: CalendarDayItem[];
    highlightStatus?: string;
    month: string;
    planBands?: CalendarPlanBand[];
    selectedDate?: string;
  }>(),
  { days: () => [], highlightStatus: undefined, planBands: () => [], selectedDate: undefined },
);

const emit = defineEmits<{
  select: [date: string, inMonth: boolean];
}>();
</script>

<template>
  <MonthGrid
    :days="props.days"
    :highlight-status="props.highlightStatus"
    :month="props.month"
    :plan-bands="props.planBands"
    :selected-date="props.selectedDate"
    @select="(date, inMonth) => emit('select', date, inMonth)"
  />
</template>
