<script lang="ts" setup>
import { computed } from 'vue';

import { IconifyIcon } from '@vben/icons';

export interface DayFlagCellState {
  bad_weather: boolean;
  high_temp: boolean;
  locked: boolean;
  promo: boolean;
  remark: string;
}

const props = defineProps<{
  cell: DayFlagCellState;
}>();

const emit = defineEmits<{
  'update:cell': [value: DayFlagCellState];
}>();

function patch<K extends keyof DayFlagCellState>(
  key: K,
  value: DayFlagCellState[K],
) {
  emit('update:cell', { ...props.cell, [key]: value });
}

const badWeather = computed({
  get: () => props.cell.bad_weather,
  set: (v: boolean) => patch('bad_weather', v),
});
const highTemp = computed({
  get: () => props.cell.high_temp,
  set: (v: boolean) => patch('high_temp', v),
});
const promo = computed({
  get: () => props.cell.promo,
  set: (v: boolean) => patch('promo', v),
});
const remark = computed({
  get: () => props.cell.remark,
  set: (v: string) => patch('remark', v),
});
</script>

<template>
  <div class="flex flex-col gap-1 text-xs">
    <a-checkbox v-model:checked="badWeather" :disabled="cell.locked">
      恶劣天气
    </a-checkbox>
    <a-checkbox v-model:checked="highTemp" :disabled="cell.locked">
      高温
    </a-checkbox>
    <a-checkbox v-model:checked="promo" :disabled="cell.locked">
      大促
    </a-checkbox>
    <a-popover trigger="click">
      <template #content>
        <a-textarea
          v-model:value="remark"
          :disabled="cell.locked"
          :rows="3"
          placeholder="备注"
        />
      </template>
      <IconifyIcon
        class="size-3.5 cursor-pointer"
        :class="cell.remark ? 'text-primary' : 'text-muted-foreground'"
        icon="lucide:sticky-note"
      />
    </a-popover>
  </div>
</template>
