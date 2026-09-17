<script lang="ts" setup>
import type { EngineField, EngineFunction } from '../../../types/engine';

import { computed, ref } from 'vue';

import {
  formulaFieldLabel,
  isManualPeriodField,
} from '../helpers';

const props = withDefaults(
  defineProps<{
    disabled?: boolean;
    fields: EngineField[];
    functions: EngineFunction[];
    stage: string;
    value?: string;
  }>(),
  { disabled: false, value: '' },
);

const emit = defineEmits<{
  'update:value': [value: string];
}>();

const numberInput = ref<null | number>(null);

const stageFields = computed(() =>
  props.fields.filter((item) => item.stages.includes(props.stage)),
);

function insert(token: string) {
  if (props.disabled) return;
  const current = props.value || '';
  const next = current ? `${current} ${token}` : token;
  emit('update:value', next);
}

function insertNumber() {
  if (numberInput.value === null || numberInput.value === undefined) return;
  insert(String(numberInput.value));
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <div>
      <div class="mb-1 text-xs">字段</div>
      <div class="flex flex-wrap gap-1">
        <a-tag
          v-for="item in stageFields"
          :key="item.name"
          :color="isManualPeriodField(item.name) ? 'orange' : undefined"
          :data-testid="
            isManualPeriodField(item.name)
              ? 'plan-manual-field-formula-chip'
              : undefined
          "
          class="cursor-pointer"
          @click="insert(item.name)"
        >
          {{ formulaFieldLabel(item.name) }}
        </a-tag>
      </div>
    </div>
    <div>
      <div class="mb-1 text-xs">函数</div>
      <div class="flex flex-wrap gap-1">
        <a-tag
          v-for="item in functions"
          :key="item.name"
          color="blue"
          class="cursor-pointer"
          @click="insert(`${item.name}()`)"
        >
          {{ item.name }}
        </a-tag>
      </div>
    </div>
    <div>
      <div class="mb-1 text-xs">运算符</div>
      <a-space>
        <a-button
          v-for="op in ['+', '-', '*', '/', '(', ')']"
          :key="op"
          :disabled="disabled"
          size="small"
          @click="insert(op)"
        >
          {{ op }}
        </a-button>
      </a-space>
    </div>
    <div class="flex items-center gap-2">
      <a-input-number v-model:value="numberInput" :disabled="disabled" placeholder="数字" />
      <a-button :disabled="disabled" size="small" @click="insertNumber">插入数字</a-button>
    </div>
    <a-input
      :value="value"
      disabled
      placeholder="点选生成的表达式"
    />
    <a-textarea
      :disabled="disabled"
      :rows="3"
      :value="value"
      placeholder="高级编辑：可直接修改表达式，保存前必须通过校验"
      @update:value="(v) => emit('update:value', String(v ?? ''))"
    />
  </div>
</template>
