<script lang="ts" setup>
import type { PlanPreset } from '../../../constants/plan-presets';

import { computed, ref } from 'vue';

import { useVbenModal } from '@vben/common-ui';

import { message } from 'antdv-next';

import {
  PLAN_PRESET_CATEGORIES,
  PLAN_PRESETS,
} from '../../../constants/plan-presets';
import { enumLabel, PLAN_MODE_TAG_OPTIONS } from '../../../constants/enums';

export type PlanPresetApplyMode = 'append' | 'replace';

const keyword = ref('');
const category = ref<string>('全部');
const selectedId = ref('C01');
const applyMode = ref<PlanPresetApplyMode>('replace');

const [Modal, modalApi] = useVbenModal({
  class: 'w-[860px]',
  confirmText: '应用案例',
  destroyOnClose: true,
  async onConfirm() {
    const preset = selected.value;
    if (!preset) {
      message.warning('请选择一个方案案例');
      return;
    }
    modalApi.getData<{
      onApply?: (preset: PlanPreset, mode: PlanPresetApplyMode) => void;
    }>()?.onApply?.(preset, applyMode.value);
    await modalApi.close();
  },
  onOpenChange(isOpen) {
    if (!isOpen) return;
    keyword.value = '';
    category.value = '全部';
    selectedId.value = PLAN_PRESETS[0]?.id ?? '';
    applyMode.value = modalApi.getData<{ defaultMode?: PlanPresetApplyMode }>()?.defaultMode ?? 'replace';
  },
});

const filtered = computed(() => {
  const q = keyword.value.trim().toLowerCase();
  return PLAN_PRESETS.filter((item) => {
    if (category.value !== '全部' && item.category !== category.value) return false;
    if (!q) return true;
    const hay = [
      item.id,
      item.name,
      item.description,
      item.expected ?? '',
      ...item.tags,
    ]
      .join(' ')
      .toLowerCase();
    return hay.includes(q);
  });
});

const selected = computed(() =>
  PLAN_PRESETS.find((item) => item.id === selectedId.value),
);

const categoryOptions = computed(() => [
  { label: '全部', value: '全部' },
  ...PLAN_PRESET_CATEGORIES.map((item) => ({ label: item, value: item })),
]);
</script>

<template>
  <Modal title="从方案案例导入">
    <div class="flex flex-col gap-3">
      <div class="flex flex-wrap gap-2">
        <a-input
          v-model:value="keyword"
          allow-clear
          class="w-[220px]"
          placeholder="搜索案例名称或标签"
        />
        <a-select
          v-model:value="category"
          :options="categoryOptions"
          class="w-[160px]"
        />
        <a-radio-group v-model:value="applyMode">
          <a-radio value="replace">替换当前全部方案项</a-radio>
          <a-radio value="append">追加到末尾</a-radio>
        </a-radio-group>
      </div>

      <div class="grid min-h-[360px] grid-cols-1 gap-3 md:grid-cols-2">
        <div class="max-h-[420px] overflow-auto rounded border">
          <button
            v-for="preset in filtered"
            :key="preset.id"
            class="flex w-full flex-col gap-1 border-b px-3 py-2 text-left last:border-b-0"
            :class="
              selectedId === preset.id
                ? 'bg-primary/5 border-l-2 border-l-primary'
                : 'hover:bg-muted/40'
            "
            type="button"
            @click="selectedId = preset.id"
          >
            <div class="flex items-center gap-2">
              <span class="text-muted-foreground text-xs">{{ preset.id }}</span>
              <span class="font-medium">{{ preset.name }}</span>
            </div>
            <div class="text-muted-foreground line-clamp-2 text-xs">
              {{ preset.description }}
            </div>
            <div class="flex flex-wrap gap-1">
              <a-tag v-for="tag in preset.tags" :key="tag" class="m-0">{{ tag }}</a-tag>
            </div>
          </button>
          <a-empty v-if="filtered.length === 0" description="无匹配案例" />
        </div>

        <div v-if="selected" class="rounded border p-3">
          <div class="mb-2 text-base font-medium">{{ selected.name }}</div>
          <div class="text-muted-foreground mb-2 text-sm">{{ selected.description }}</div>
          <div class="mb-2 flex flex-wrap gap-2 text-sm">
            <span>
              模式：
              {{ enumLabel(PLAN_MODE_TAG_OPTIONS, selected.mode_tag) }}
            </span>
            <span>方案项：{{ selected.items.length }} 条</span>
          </div>
          <div v-if="selected.expected" class="mb-3 rounded bg-muted/40 px-2 py-1 text-sm">
            试算参考：{{ selected.expected }}
          </div>
          <div class="text-sm font-medium">包含方案项</div>
          <ul class="mt-2 max-h-[220px] list-disc space-y-1 overflow-auto pl-5 text-sm">
            <li v-for="(item, index) in selected.items" :key="index">
              [{{ item.stage }}] {{ item.name }}（{{ item.subject_code }}）
            </li>
          </ul>
        </div>
      </div>
    </div>
  </Modal>
</template>
