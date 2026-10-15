<script lang="ts" setup>
import type { EngineField } from '../../../types/engine';
import type { LadderTier } from '../../../types/plan';

import { computed, ref } from 'vue';

import { IconifyIcon } from '@vben/icons';

import MoneyText from '../../../components/MoneyText.vue';
import { previewLadder, previewOrderQuantity } from './ladder-preview';

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

const demoOpen = ref(false);
const sample = ref<number>(5);
const orderCount = ref<number>(100);

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

const fieldName = computed(() => String(props.value.字段 || '字段'));
const fieldUnit = computed(
  () => props.fields.find((item) => item.name === fieldName.value)?.unit || '',
);
const countField = computed(() => fieldUnit.value === '单');
const ladderMode = computed(() => String(props.value.模式 || ''));
const ladderPricing = computed(() => String(props.value.计价 || ''));

const probe = computed(() =>
  previewLadder(Number(sample.value), ladderMode.value, ladderPricing.value, tiers.value),
);

const quantityPreview = computed(() =>
  previewOrderQuantity({
    countField: countField.value,
    fieldName: fieldName.value,
    mode: ladderMode.value,
    orderCount: Number(orderCount.value),
    pricing: ladderPricing.value,
    sample: probe.value,
    sampleValue: Number(sample.value),
    tiers: tiers.value,
  }),
);

const quantityHint = computed(() =>
  countField.value
    ? `填写订单数量，按「${fieldName.value}」代入阶梯`
    : `先填每单的「${fieldName.value}」，再按订单数量汇总`,
);
</script>

<template>
  <div class="flex flex-col gap-3">
    <div class="flex min-w-0 flex-col gap-3">
      <div class="flex flex-wrap gap-3">
        <div>
          <div class="mb-1 text-xs">字段</div>
          <a-select
            :disabled="disabled"
            :options="numberFields.map((item) => ({ label: item.name, value: item.name }))"
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
      <div class="flex flex-wrap gap-2">
        <a-button :disabled="disabled" @click="addTier">添加档位</a-button>
        <a-button @click="demoOpen = true">演示</a-button>
      </div>
      <div v-if="ladderErrors.length" class="text-sm text-red-500">
        {{ ladderErrors.join('；') }}
      </div>
    </div>

    <a-modal
      v-model:open="demoOpen"
      :footer="null"
      title="按订单数量算金额"
      width="420px"
    >
      <div class="flex flex-col gap-3">
        <div class="text-muted-foreground text-xs">
          {{ ladderMode || '未选模式' }} · {{ ladderPricing || '未选计价' }}
          · {{ quantityHint }}
        </div>
        <div v-if="!countField">
          <div class="mb-1 text-xs">
            每单{{ fieldName }}{{ fieldUnit ? `（${fieldUnit}）` : '' }}
          </div>
          <a-input-number v-model:value="sample" class="w-full" />
        </div>
        <div>
          <div class="mb-1 text-xs">订单数量（单）</div>
          <a-input-number
            v-model:value="orderCount"
            :min="0"
            :precision="0"
            class="w-full"
          />
        </div>
        <div class="rounded-md bg-muted/40 px-3 py-3">
          <div class="text-muted-foreground text-xs">模拟金额</div>
          <div class="mt-1 text-2xl font-semibold leading-none">
            <MoneyText :value="quantityPreview.amount" />
            <span class="ml-1 text-sm font-normal">元</span>
          </div>
          <div v-if="quantityPreview.error" class="mt-2 text-xs text-red-500">
            {{ quantityPreview.error }}
          </div>
          <div v-else class="text-muted-foreground mt-2 text-xs">
            {{ quantityPreview.note }}
          </div>
        </div>
        <ul v-if="quantityPreview.slices.length" class="space-y-1 text-xs">
          <li
            v-for="(slice, index) in quantityPreview.slices"
            :key="`${slice.label}-${index}`"
            class="flex items-start justify-between gap-3"
          >
            <span class="text-muted-foreground">{{ slice.label }}</span>
            <span class="shrink-0">
              <MoneyText :value="slice.amount" />
              元
            </span>
          </li>
        </ul>
      </div>
    </a-modal>
  </div>
</template>
