<script lang="ts" setup>
import type { SiteResult } from '../types/site';

import { computed, onMounted, ref } from 'vue';

import { getAllSitesApi } from '../api/site';

const props = withDefaults(
  defineProps<{
    allowAll?: boolean;
    allowClear?: boolean;
    disabled?: boolean;
    placeholder?: string;
    value?: null | number;
  }>(),
  {
    allowAll: false,
    allowClear: true,
    disabled: false,
    placeholder: '请选择站点',
    value: undefined,
  },
);

const emit = defineEmits<{
  change: [value: null | number | undefined];
  'update:value': [value: null | number | undefined];
}>();

const loading = ref(false);
const sites = ref<SiteResult[]>([]);

const options = computed(() => {
  const list = sites.value.map((item) => ({
    label: `${item.name}（${item.code}）`,
    value: item.id,
  }));
  if (props.allowAll) {
    return [{ label: '全部站点', value: 0 }, ...list];
  }
  return list;
});

async function load() {
  loading.value = true;
  try {
    sites.value = (await getAllSitesApi()) ?? [];
  } catch {
    sites.value = [];
  } finally {
    loading.value = false;
  }
}

function onChange(val: any) {
  const next = val === 0 && props.allowAll ? null : (val as null | number | undefined);
  emit('update:value', next);
  emit('change', next);
}

onMounted(load);

defineExpose({ reload: load });
</script>

<template>
  <a-select
    :allow-clear="allowClear"
    :disabled="disabled"
    :loading="loading"
    :options="options"
    :placeholder="placeholder"
    :value="value === null && allowAll ? 0 : value"
    class="min-w-[180px]"
    show-search
    option-filter-prop="label"
    @update:value="onChange"
  />
</template>
