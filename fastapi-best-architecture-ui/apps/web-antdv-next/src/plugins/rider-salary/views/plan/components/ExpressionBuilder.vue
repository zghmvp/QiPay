<script lang="ts" setup>
import type { EngineField, EngineFunction } from '../../../types/engine';

import { computed, ref } from 'vue';

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

// 手工奖惩已经按明细计入应发，公式里再引用会重复计发
const DUPLICATED_FIELDS = ['本期手工奖', '本期手工惩'];
const duplicateHint = computed(() =>
  DUPLICATED_FIELDS.filter((name) => (props.value || '').includes(name)),
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
          class="cursor-pointer"
          @click="insert(item.name)"
        >
          {{ item.name }}
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
    <a-alert
      v-if="duplicateHint.length > 0"
      type="warning"
      show-icon
      :message="`「${duplicateHint.join('、')}」已随手工奖惩明细计入应发，公式中再次引用会重复计发，请确认这是有意的`"
    />
  </div>
</template>
