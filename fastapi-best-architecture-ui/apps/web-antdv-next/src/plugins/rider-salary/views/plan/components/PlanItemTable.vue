<script lang="ts" setup>
import type { PlanItemDraft } from '../../../types/plan';

import { computed } from 'vue';

import { IconifyIcon } from '@vben/icons';

import { CALC_STAGE_OPTIONS, enumLabel } from '../../../constants/enums';
import {
  createDraftItem,
  findMisplacedGuaranteeKeys,
  isGuaranteeLikeItem,
  STAGE_ORDER,
  summarizeCondition,
  summarizeFormula,
} from '../helpers';

const props = withDefaults(
  defineProps<{
    disabled?: boolean;
    items: PlanItemDraft[];
    selectedKey?: string;
    subjectNameOf?: (id?: number) => string;
  }>(),
  { disabled: false, selectedKey: '', subjectNameOf: () => '—' },
);

const emit = defineEmits<{
  select: [key: string];
  'update:items': [items: PlanItemDraft[]];
}>();

const grouped = computed(() =>
  STAGE_ORDER.map((stage) => ({
    items: props.items.filter((item) => item.stage === stage),
    stage,
    title: enumLabel(CALC_STAGE_OPTIONS, stage),
  })),
);

const misplacedGuaranteeKeys = computed(
  () => new Set(findMisplacedGuaranteeKeys(props.items)),
);

function replace(next: PlanItemDraft[]) {
  emit('update:items', next);
}

function addItem(stage: string) {
  const item = createDraftItem(stage);
  replace([...props.items, item]);
  emit('select', item._key);
}

function removeItem(key: string) {
  const next = props.items.filter((item) => item._key !== key);
  replace(next);
  if (props.selectedKey === key) {
    emit('select', next[0]?._key ?? '');
  }
}

function toggleEnabled(key: string, enabled: boolean) {
  replace(
    props.items.map((item) => (item._key === key ? { ...item, enabled } : item)),
  );
}

function move(stage: string, index: number, delta: number) {
  const group = props.items.filter((item) => item.stage === stage);
  const target = index + delta;
  if (target < 0 || target >= group.length) return;
  const current = group[index]!;
  group[index] = group[target]!;
  group[target] = current;
  const others = props.items.filter((item) => item.stage !== stage);
  const order = STAGE_ORDER.flatMap((s) =>
    s === stage ? group : others.filter((item) => item.stage === s),
  );
  replace(order);
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <div
      v-for="group in grouped"
      :key="group.stage"
      class="rounded border border-border"
    >
      <div class="flex items-center justify-between border-b px-3 py-2">
        <span class="font-medium">{{ group.title }}（{{ group.items.length }}）</span>
        <a-button
          :disabled="disabled"
          size="small"
          type="link"
          @click="addItem(group.stage)"
        >
          添加{{ group.title }}项
        </a-button>
      </div>
      <a-empty v-if="group.items.length === 0" description="暂无方案项" />
      <div v-else class="divide-y">
        <button
          v-for="(item, index) in group.items"
          :key="item._key"
          class="flex w-full items-start gap-2 px-3 py-2 text-left"
          :class="selectedKey === item._key ? 'bg-primary/5' : 'hover:bg-muted/40'"
          type="button"
          @click="emit('select', item._key)"
        >
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <span class="truncate font-medium">{{ item.name || '未命名' }}</span>
              <span class="text-muted-foreground truncate text-xs">
                {{ subjectNameOf(item.subject_id) }}
              </span>
              <a-tag
                v-if="isGuaranteeLikeItem(item) && misplacedGuaranteeKeys.has(item._key)"
                color="warning"
              >
                建议沉底
              </a-tag>
              <a-tag v-else-if="isGuaranteeLikeItem(item)" color="blue">
                保底
              </a-tag>
            </div>
            <div class="text-muted-foreground mt-1 truncate text-xs">
              条件：{{ summarizeCondition(item.condition_json, item.condition_expr) }}
            </div>
            <div class="text-muted-foreground truncate text-xs">
              公式：{{ summarizeFormula(item.formula_json, item.formula_expr) }}
            </div>
          </div>
          <div class="flex flex-col items-end gap-1" @click.stop>
            <a-switch
              :checked="item.enabled"
              :disabled="disabled"
              size="small"
              @update:checked="(v) => toggleEnabled(item._key, Boolean(v))"
            />
            <a-space>
              <a-button
                :disabled="disabled"
                size="small"
                type="text"
                @click="move(group.stage, index, -1)"
              >
                <IconifyIcon class="size-3.5" icon="lucide:arrow-up" />
              </a-button>
              <a-button
                :disabled="disabled"
                size="small"
                type="text"
                @click="move(group.stage, index, 1)"
              >
                <IconifyIcon class="size-3.5" icon="lucide:arrow-down" />
              </a-button>
              <a-button
                :disabled="disabled"
                danger
                size="small"
                type="text"
                @click="removeItem(item._key)"
              >
                <IconifyIcon class="size-3.5" icon="lucide:trash-2" />
              </a-button>
            </a-space>
          </div>
        </button>
      </div>
    </div>
  </div>
</template>
