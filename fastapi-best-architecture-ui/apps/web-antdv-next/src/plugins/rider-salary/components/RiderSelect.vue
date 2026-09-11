<script lang="ts" setup>
import type { RiderResult } from '../types/rider';

import { computed, ref, watch } from 'vue';

import { getRiderListApi } from '../api/rider';

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
    placeholder: '请选择骑手',
    siteId: undefined,
    value: undefined,
  },
);

const emit = defineEmits<{
  change: [value: null | number | undefined, row?: RiderResult];
  'update:value': [value: null | number | undefined];
}>();

const loading = ref(false);
const keyword = ref('');
const riders = ref<RiderResult[]>([]);
let timer: null | ReturnType<typeof setTimeout> = null;

const options = computed(() =>
  riders.value.map((item) => ({
    label: `${item.job_no} ${item.name}`,
    value: item.id,
  })),
);

async function load(search?: string) {
  if (!props.siteId) {
    riders.value = [];
    return;
  }
  loading.value = true;
  try {
    const res = await getRiderListApi({
      keyword: search || undefined,
      page: 1,
      size: 50,
      site_id: props.siteId,
    });
    riders.value = res?.items ?? [];
  } catch {
    riders.value = [];
  } finally {
    loading.value = false;
  }
}

function onSearch(val: string) {
  keyword.value = val;
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => load(val), 300);
}

function onChange(val: any) {
  const next = (val ?? undefined) as null | number | undefined;
  emit('update:value', next);
  const row = riders.value.find((item) => item.id === next);
  emit('change', next, row);
}

watch(
  () => props.siteId,
  (next, prev) => {
    if (prev !== undefined && next !== prev) {
      emit('update:value', undefined);
    }
    load();
  },
  { immediate: true },
);
</script>

<template>
  <a-select
    :allow-clear="allowClear"
    :disabled="disabled || !siteId"
    :filter-option="false"
    :loading="loading"
    :not-found-content="siteId ? '暂无骑手' : '请先选择站点'"
    :options="options"
    :placeholder="placeholder"
    :value="value"
    class="min-w-[180px]"
    show-search
    @search="onSearch"
    @update:value="onChange"
  />
</template>
