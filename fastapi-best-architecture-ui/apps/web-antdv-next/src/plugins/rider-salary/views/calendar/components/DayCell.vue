<script lang="ts" setup>
import type { CalendarDayItem } from '../../../types/calendar';

import { computed } from 'vue';

import { IconifyIcon } from '@vben/icons';

import MoneyText from '../../../components/MoneyText.vue';

const props = defineProps<{
  date: string;
  inMonth: boolean;
  item?: CalendarDayItem;
  selected?: boolean;
  today?: boolean;
}>();

const emit = defineEmits<{
  click: [];
}>();

const status = computed(() => props.item?.day_status);
const dayNo = computed(() => String(props.date).slice(8, 10).replace(/^0/, ''));
const orderText = computed(() => {
  if (!props.inMonth) return '';
  if (!props.item) return '—';
  if (status.value === 'not_imported' || status.value === 'no_orders') {
    return '—';
  }
  return String(props.item.order_count);
});

const subjects = computed(() => (props.item?.subjects ?? []).slice(0, 3));
const showNet = computed(() => {
  const n = Number(props.item?.net_adjust ?? 0);
  return Number.isFinite(n) && Math.abs(n) >= 0.005;
});

const tooltip = computed(() => {
  if (!props.inMonth) return undefined;
  if (status.value === 'not_imported') return '未导入';
  if (status.value === 'no_plan') return '无方案';
  if (status.value === 'no_orders') return '无数据';
  if (props.item?.is_locked) return '已锁账';
  return undefined;
});
</script>

<template>
  <a-tooltip :title="tooltip">
    <button
      class="relative flex h-full min-h-[110px] w-full flex-col items-stretch rounded-sm px-1.5 pb-1.5 pt-5 text-left"
      :class="{
        'opacity-40': !inMonth,
        'day-not-imported border border-dashed border-[#d9d9d9]':
          inMonth && status === 'not_imported',
        'bg-[#fafafa]': inMonth && status === 'no_orders',
        'bg-[#fff7e6]': inMonth && status === 'no_plan',
        'ring-2 ring-[#1677ff]': today,
        'bg-primary/5': selected && inMonth,
      }"
      type="button"
      @click="emit('click')"
    >
      <div class="absolute left-1.5 top-5 text-xs leading-none">{{ dayNo }}</div>
      <div class="absolute right-1 top-5 flex items-center gap-0.5">
        <IconifyIcon
          v-if="inMonth && status === 'no_plan'"
          class="size-3.5 text-red-500"
          icon="lucide:circle-alert"
        />
        <IconifyIcon
          v-if="inMonth && item?.is_locked"
          class="size-3.5 text-orange-500"
          icon="lucide:lock"
        />
      </div>
      <div
        class="mt-2 flex flex-1 items-center justify-center text-xl font-semibold leading-none"
        :class="
          status === 'no_orders' || status === 'not_imported'
            ? 'text-muted-foreground'
            : ''
        "
      >
        {{ orderText }}
      </div>
      <div
        v-if="inMonth && item && (showNet || subjects.length)"
        class="mt-1 truncate text-[11px] leading-tight"
      >
        <MoneyText v-if="showNet" signed :value="item.net_adjust" />
        <span v-if="subjects.length" class="text-muted-foreground ml-1">
          {{ subjects.join(' ') }}
        </span>
      </div>
    </button>
  </a-tooltip>
</template>

<style scoped>
.day-not-imported {
  background-image: repeating-linear-gradient(
    45deg,
    #f0f0f0,
    #f0f0f0 6px,
    #fafafa 6px,
    #fafafa 12px
  );
}
</style>
