<script lang="ts" setup>
import type { PeriodResult } from '../types/period';

import { computed, ref, watch } from 'vue';

import { getPeriodApi, getPeriodListApi } from '../api/period';
import { enumLabel, PERIOD_STATUS_OPTIONS } from '../constants/enums';

const props = withDefaults(
  defineProps<{
    allowClear?: boolean;
    disabled?: boolean;
    placeholder?: string;
    siteId?: null | number;
    value?: null | number;
  }>(),
  {
    allowClear: true,
    disabled: false,
    placeholder: '请选择本站周期',
    siteId: undefined,
    value: undefined,
  },
);

const emit = defineEmits<{
  change: [value: null | number | undefined, row?: PeriodResult];
  'update:value': [value: null | number | undefined];
}>();

const loading = ref(false);
const periods = ref<PeriodResult[]>([]);

function periodLabel(row: PeriodResult) {
  const range = `${row.start_date} ~ ${row.end_date}`;
  const status =
    row.status_label || enumLabel(PERIOD_STATUS_OPTIONS, row.status);
  if (row.rider_id) {
    const who = row.rider_job_no || row.rider_name || `骑手#${row.rider_id}`;
    return `${range} · ${who}（${status}）`;
  }
  return `${range}（${status}）`;
}

const options = computed(() =>
  periods.value.map((item) => ({
    label: periodLabel(item),
    value: item.id,
  })),
);

async function load() {
  if (!props.siteId) {
    periods.value = [];
    return;
  }
  loading.value = true;
  try {
    const res = await getPeriodListApi({
      page: 1,
      site_id: props.siteId,
      size: 200,
    });
    periods.value = (res?.items ?? []).filter(
      (item) => item.site_id === props.siteId,
    );
    await ensureCurrentValue();
  } catch {
    periods.value = [];
  } finally {
    loading.value = false;
  }
}

async function ensureCurrentValue() {
  const id = props.value;
  if (!id || !props.siteId) return;
  if (periods.value.some((item) => item.id === id)) return;
  try {
    const row = await getPeriodApi(id);
    if (row.site_id === props.siteId) {
      periods.value = [row, ...periods.value];
    } else {
      emit('update:value', undefined);
      emit('change', undefined);
    }
  } catch {
    emit('update:value', undefined);
    emit('change', undefined);
  }
}

function onChange(val: unknown) {
  const next = (val ?? undefined) as null | number | undefined;
  emit('update:value', next);
  const row = periods.value.find((item) => item.id === next);
  emit('change', next, row);
}

watch(
  () => props.siteId,
  (next, prev) => {
    if (prev !== undefined && next !== prev) {
      emit('update:value', undefined);
      emit('change', undefined);
    }
    void load();
  },
  { immediate: true },
);

watch(
  () => props.value,
  () => {
    void ensureCurrentValue();
  },
);
</script>

<template>
  <a-select
    :allow-clear="allowClear"
    :disabled="disabled || !siteId"
    :loading="loading"
    :not-found-content="siteId ? '本站暂无周期' : '请先选择站点'"
    :options="options"
    :placeholder="placeholder"
    :value="value"
    class="min-w-[220px]"
    data-testid="payroll-period-picker"
    option-filter-prop="label"
    show-search
    @update:value="onChange"
  />
</template>
