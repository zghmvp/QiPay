<script lang="ts" setup>
import type { CalcRiderOption } from '../../../types/period';

import { computed, ref, watch } from 'vue';

import { getPeriodCalcRidersApi } from '../../../api/period';
import { getRiderApi } from '../../../api/rider';

const UNSELECTED_ALL = '未选 = 计算本周期全部骑手';

const props = withDefaults(
  defineProps<{
    disabled?: boolean;
    periodId?: number;
    value?: number[];
  }>(),
  {
    disabled: false,
    periodId: undefined,
    value: () => [],
  },
);

const emit = defineEmits<{
  'update:value': [value: number[]];
}>();

const loading = ref(false);
const keyword = ref('');
const riders = ref<CalcRiderOption[]>([]);
const extraSelected = ref<CalcRiderOption[]>([]);
const truncated = ref(false);
const truncatedHint = ref('');
const unselectedMeansAll = ref(UNSELECTED_ALL);
let timer: null | ReturnType<typeof setTimeout> = null;
let fetchSeq = 0;

const selectedIds = computed(() => props.value ?? []);

const options = computed(() => {
  const seen = new Set<number>();
  const rows: { label: string; value: number }[] = [];
  for (const item of [...extraSelected.value, ...riders.value]) {
    if (seen.has(item.id)) continue;
    seen.add(item.id);
    rows.push({ label: `${item.job_no} ${item.name}`, value: item.id });
  }
  return rows;
});

async function loadList(search?: string) {
  if (!props.periodId) {
    riders.value = [];
    truncated.value = false;
    truncatedHint.value = '';
    return;
  }
  const seq = ++fetchSeq;
  loading.value = true;
  try {
    const res = await getPeriodCalcRidersApi(props.periodId, {
      keyword: search || undefined,
      page: 1,
      size: 200,
    });
    if (seq !== fetchSeq) return;
    riders.value = res?.items ?? [];
    truncated.value = Boolean(res?.truncated);
    truncatedHint.value =
      res?.truncated_hint ||
      (res?.truncated ? `仅列出前 ${res.size || 200} 人，其余请搜索` : '');
    unselectedMeansAll.value = res?.unselected_means_all || UNSELECTED_ALL;
  } catch {
    if (seq !== fetchSeq) return;
    riders.value = [];
    truncated.value = false;
    truncatedHint.value = '';
  } finally {
    if (seq === fetchSeq) loading.value = false;
  }
}

async function ensureSelectedVisible(ids: number[]) {
  const known = new Set([
    ...riders.value.map((item) => item.id),
    ...extraSelected.value.map((item) => item.id),
  ]);
  const missing = ids.filter((id) => !known.has(id));
  if (!missing.length) return;
  const fetched: CalcRiderOption[] = [];
  await Promise.all(
    missing.map(async (id) => {
      try {
        const row = await getRiderApi(id);
        if (row?.id) {
          fetched.push({ id: row.id, job_no: row.job_no, name: row.name });
        }
      } catch {
        /* 选中项拉失败时仍保留 id */
      }
    }),
  );
  if (!fetched.length) return;
  const have = new Set(extraSelected.value.map((item) => item.id));
  extraSelected.value = [
    ...extraSelected.value,
    ...fetched.filter((item) => !have.has(item.id)),
  ];
}

function onSearch(val: string) {
  keyword.value = val;
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => {
    void loadList(val.trim());
  }, 300);
}

function onChange(val: unknown) {
  const next = Array.isArray(val)
    ? val.map((item) => Number(item)).filter((n) => Number.isFinite(n) && n > 0)
    : [];
  emit('update:value', next);
}

watch(
  () => props.periodId,
  () => {
    extraSelected.value = [];
    keyword.value = '';
    void loadList();
  },
  { immediate: true },
);

watch(
  selectedIds,
  (ids) => {
    void ensureSelectedVisible(ids);
  },
  { immediate: true },
);
</script>

<template>
  <div class="flex min-w-[280px] flex-1 flex-col gap-1">
    <div
      class="text-sm text-muted-foreground"
      data-testid="period-calc-riders-unselected-all"
    >
      {{ unselectedMeansAll }}。勾选后只算选中的人，选中以外不算。
    </div>
    <a-select
      :value="selectedIds"
      allow-clear
      class="w-full"
      data-testid="period-calc-riders"
      mode="multiple"
      placeholder="搜索工号或姓名；留空即全量"
      show-search
      :disabled="disabled"
      :filter-option="false"
      :loading="loading"
      :options="options"
      :not-found-content="periodId ? '暂无骑手' : '请先打开周期'"
      @search="onSearch"
      @update:value="onChange"
    />
    <div
      v-if="truncated && truncatedHint"
      class="text-sm text-amber-600"
      data-testid="period-calc-riders-truncated"
    >
      {{ truncatedHint }}
    </div>
  </div>
</template>
