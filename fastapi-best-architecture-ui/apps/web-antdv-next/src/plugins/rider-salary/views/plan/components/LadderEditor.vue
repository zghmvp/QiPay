<script lang="ts" setup>
import type { EngineField } from '../../../types/engine';
import type { LadderTier } from '../../../types/plan';

import { computed, ref, watch } from 'vue';

import { IconifyIcon } from '@vben/icons';

import { evaluateSampleApi } from '../../../api/engine';
import MoneyText from '../../../components/MoneyText.vue';
import { formulaFieldLabel } from '../helpers';

const props = withDefaults(
  defineProps<{
    disabled?: boolean;
    fields: EngineField[];
    stage: string;
    value: Record<string, unknown>;
  }>(),
  { disabled: false },
);

const emit = defineEmits<{
  'update:value': [value: Record<string, unknown>];
}>();

const sample = ref<number>(5);
const sampleAmount = ref<null | number>(null);
const sampleHit = ref(true);
const sampleError = ref('');
let timer: null | ReturnType<typeof setTimeout> = null;

const numberFields = computed(() =>
  props.fields.filter(
    (item) => item.type === 'number' && item.stages.includes(props.stage),
  ),
);

const tiers = computed<LadderTier[]>(() => {
  const raw = props.value.档位;
  return Array.isArray(raw) ? (raw as LadderTier[]) : [];
});

const ladderErrors = computed(() => {
  const list = tiers.value;
  const errors: string[] = [];
  if (list.length < 1) errors.push('至少需要 1 档');
  if (list[0] && Number(list[0].下限) !== 0) {
    errors.push('阶梯第一档下限必须为 0');
  }
  list.forEach((tier, index) => {
    const next = list[index + 1];
    if (index < list.length - 1 && (tier.上限 === null || tier.上限 === undefined)) {
      errors.push('仅最后一档上限可为空');
    }
    if (next && tier.上限 !== next.下限) {
      errors.push('阶梯档位必须连续、不能重叠');
    }
  });
  return [...new Set(errors)];
});

function patch(partial: Record<string, unknown>) {
  emit('update:value', { ...props.value, 类型: '阶梯', ...partial });
}

function updateTier(index: number, partial: Partial<LadderTier>) {
  const next = tiers.value.map((tier, i) =>
    i === index ? { ...tier, ...partial } : { ...tier },
  );
  if (partial.上限 !== undefined && next[index + 1]) {
    next[index + 1] = { ...next[index + 1]!, 下限: Number(partial.上限 ?? 0) };
  }
  patch({ 档位: next });
}

function addTier() {
  const last = tiers.value[tiers.value.length - 1];
  const next = [...tiers.value];
  const link = last?.上限 ?? (last ? Number(last.下限) + 100 : 0);
  if (last && (last.上限 === null || last.上限 === undefined)) {
    next[next.length - 1] = { ...last, 上限: link };
  }
  next.push({ 上限: null, 下限: link, 值: last?.值 ?? 0 });
  patch({ 档位: next });
}

function removeTier(index: number) {
  patch({ 档位: tiers.value.filter((_, i) => i !== index) });
}

function moveTier(index: number, delta: number) {
  const target = index + delta;
  if (target < 0 || target >= tiers.value.length) return;
  const next = [...tiers.value];
  const current = next[index]!;
  next[index] = next[target]!;
  next[target] = current;
  patch({ 档位: next });
}

async function runSample() {
  sampleError.value = '';
  try {
    const res = await evaluateSampleApi({
      condition_json: {},
      context: { [String(props.value.字段 || '配送距离')]: sample.value },
      formula_json: props.value,
      stage: props.stage,
    });
    sampleHit.value = res.hit;
    sampleAmount.value = res.amount;
    if (res.trace?.错误) {
      sampleError.value = Array.isArray(res.trace.错误)
        ? res.trace.错误.join('；')
        : String(res.trace.错误);
    }
  } catch {
    sampleError.value = '预览求值失败';
  }
}

watch(
  () => [props.value, sample.value, props.stage],
  () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(runSample, 400);
  },
  { deep: true, immediate: true },
);
</script>

<template>
  <div class="flex flex-col gap-3 lg:flex-row">
    <div class="flex min-w-0 flex-1 flex-col gap-3">
      <div class="flex flex-wrap gap-3">
        <div>
          <div class="mb-1 text-xs">字段</div>
          <a-select
            :disabled="disabled"
            :options="
              numberFields.map((item) => ({
                label: formulaFieldLabel(item.name),
                value: item.name,
              }))
            "
            :value="value.字段"
            class="min-w-[160px]"
            @update:value="(v) => patch({ 字段: String(v ?? '') })"
          />
        </div>
        <div>
          <div class="mb-1 text-xs">模式</div>
          <a-radio-group
            :disabled="disabled"
            :value="value.模式"
            @update:value="(v) => patch({ 模式: String(v ?? '') })"
          >
            <a-radio-button value="全量落档">全量落档</a-radio-button>
            <a-radio-button value="分段累进">分段累进</a-radio-button>
          </a-radio-group>
        </div>
        <div>
          <div class="mb-1 text-xs">计价</div>
          <a-radio-group
            :disabled="disabled"
            :value="value.计价"
            @update:value="(v) => patch({ 计价: String(v ?? '') })"
          >
            <a-radio-button value="按单价">按单价</a-radio-button>
            <a-radio-button value="固定金额">固定金额</a-radio-button>
          </a-radio-group>
        </div>
      </div>
      <a-alert
        v-if="value.模式 === '分段累进' && value.计价 === '固定金额'"
        type="warning"
        show-icon
        message="分段累进通常与「按单价」配合，请确认档位「值」表示该段单价。"
      />
      <div class="overflow-x-auto">
        <div class="text-muted-foreground mb-1 grid grid-cols-[1fr_1fr_1fr_90px] gap-2 text-xs">
          <span>下限</span>
          <span>上限（空=无上限）</span>
          <span>值</span>
          <span>操作</span>
        </div>
        <div
          v-for="(record, index) in tiers"
          :key="`${record.下限}-${index}`"
          class="mb-2 grid grid-cols-[1fr_1fr_1fr_90px] items-center gap-2"
        >
          <a-input-number
            :disabled="disabled || index === 0"
            :value="record.下限"
            class="w-full"
            @update:value="(v) => updateTier(index, { 下限: Number(v ?? 0) })"
          />
          <a-input-number
            :disabled="disabled"
            :value="record.上限 ?? undefined"
            class="w-full"
            placeholder="无上限"
            @update:value="(v) => updateTier(index, { 上限: v == null ? null : Number(v) })"
          />
          <a-input-number
            :disabled="disabled"
            :precision="4"
            :value="record.值"
            class="w-full"
            @update:value="(v) => updateTier(index, { 值: Number(v ?? 0) })"
          />
          <a-space>
            <a-button :disabled="disabled" size="small" type="text" @click="moveTier(index, -1)">
              <IconifyIcon class="size-3.5" icon="lucide:arrow-up" />
            </a-button>
            <a-button :disabled="disabled" size="small" type="text" @click="moveTier(index, 1)">
              <IconifyIcon class="size-3.5" icon="lucide:arrow-down" />
            </a-button>
            <a-button :disabled="disabled" danger size="small" type="text" @click="removeTier(index)">
              <IconifyIcon class="size-3.5" icon="lucide:trash-2" />
            </a-button>
          </a-space>
        </div>
      </div>
      <a-button :disabled="disabled" @click="addTier">添加档位</a-button>
      <div v-if="ladderErrors.length" class="text-sm text-red-500">
        {{ ladderErrors.join('；') }}
      </div>
    </div>
    <div class="w-full rounded border p-3 lg:w-[220px]">
      <div class="mb-2 text-sm font-medium">即时示例</div>
      <a-input-number v-model:value="sample" class="w-full" />
      <div class="mt-2 text-sm">
        结果：
        <MoneyText :value="sampleAmount" />
        <span class="text-muted-foreground ml-1">{{ sampleHit ? '命中' : '未命中' }}</span>
      </div>
      <div v-if="sampleError" class="mt-1 text-xs text-red-500">{{ sampleError }}</div>
    </div>
  </div>
</template>
