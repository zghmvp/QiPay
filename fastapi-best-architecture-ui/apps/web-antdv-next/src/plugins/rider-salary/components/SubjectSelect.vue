<script lang="ts" setup>
import type { SubjectResult } from '../types/subject';

import { computed, onMounted, ref } from 'vue';

import { getAllSubjectsApi } from '../api/subject';

const props = withDefaults(
  defineProps<{
    allowClear?: boolean;
    direction?: string;
    disabled?: boolean;
    placeholder?: string;
    status?: string;
    value?: null | number;
  }>(),
  {
    allowClear: true,
    direction: undefined,
    disabled: false,
    placeholder: '请选择科目',
    status: 'enable',
    value: undefined,
  },
);

const emit = defineEmits<{
  change: [value: null | number | undefined, row?: SubjectResult];
  'update:value': [value: null | number | undefined];
}>();

const loading = ref(false);
const subjects = ref<SubjectResult[]>([]);

const options = computed(() =>
  subjects.value
    .filter((item) => {
      if (props.status && item.status !== props.status) return false;
      if (props.direction && item.direction !== props.direction) return false;
      return true;
    })
    .map((item) => ({
      label: `${item.name}（${item.direction_label || item.direction}）`,
      value: item.id,
    })),
);

async function load() {
  loading.value = true;
  try {
    subjects.value = (await getAllSubjectsApi()) ?? [];
  } catch {
    subjects.value = [];
  } finally {
    loading.value = false;
  }
}

function onChange(val: any) {
  const next = (val ?? undefined) as null | number | undefined;
  emit('update:value', next);
  const row = subjects.value.find((item) => item.id === next);
  emit('change', next, row);
}

onMounted(load);

defineExpose({
  find: (id?: null | number) => subjects.value.find((item) => item.id === id),
  list: subjects,
  reload: load,
});
</script>

<template>
  <a-select
    :allow-clear="allowClear"
    :disabled="disabled"
    :loading="loading"
    :options="options"
    :placeholder="placeholder"
    :value="value"
    class="min-w-[180px]"
    option-filter-prop="label"
    show-search
    @update:value="onChange"
  />
</template>
