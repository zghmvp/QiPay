<script lang="ts" setup>
import type { EngineField, EngineValidateResult } from '../../../types/engine';
import type { ConditionGroup } from '../../../types/plan';

import { onBeforeUnmount, ref, watch } from 'vue';

import { message } from 'antdv-next';

import { validateEngineApi } from '../../../api/engine';
import { fromConditionJson, toConditionJson } from '../helpers';
import ConditionGroupNode from './ConditionGroupNode.vue';

const props = withDefaults(
  defineProps<{
    disabled?: boolean;
    fields: EngineField[];
    operatorsByType?: Record<string, string[]>;
    stage: string;
    value?: null | Record<string, unknown>;
  }>(),
  { disabled: false, operatorsByType: () => ({}), value: () => ({}) },
);

const emit = defineEmits<{
  'update:value': [value: Record<string, unknown>];
}>();

const group = ref<ConditionGroup>(fromConditionJson(props.value));
const preview = ref<EngineValidateResult>({
  condition_expr: 'True',
  errors: [],
  formula_expr: '0',
  ok: true,
});
let timer: null | ReturnType<typeof setTimeout> = null;

watch(
  () => props.value,
  (next) => {
    group.value = fromConditionJson(next);
  },
);

watch(
  () => props.stage,
  (stage, prev) => {
    if (!prev || stage === prev) return;
    const names = new Set(
      props.fields.filter((item) => item.stages.includes(stage)).map((item) => item.name),
    );
    const hasInvalid = JSON.stringify(group.value).match(/"字段":"([^"]+)"/g);
    if (
      hasInvalid?.some((token) => {
        const name = token.replace('"字段":"', '').replace('"', '');
        return name && !names.has(name);
      })
    ) {
      message.warning('已切换计算阶段，请重新选择条件字段');
      group.value = fromConditionJson({});
      emit('update:value', {});
    }
  },
);

function onGroupUpdate(next: ConditionGroup) {
  group.value = next;
  emit('update:value', toConditionJson(next) ?? {});
}

async function runValidate() {
  try {
    preview.value = await validateEngineApi({
      condition_json: toConditionJson(group.value),
      formula_json: { 类型: '固定金额', 金额: 0 },
      stage: props.stage,
    });
  } catch {
    preview.value = {
      condition_expr: '',
      errors: ['校验请求失败'],
      formula_expr: '',
      ok: false,
    };
  }
}

watch(
  [group, () => props.stage],
  () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(runValidate, 500);
  },
  { deep: true, immediate: true },
);

onBeforeUnmount(() => {
  if (timer) clearTimeout(timer);
});
</script>

<template>
  <div class="flex flex-col gap-2">
    <div class="text-sm font-medium">触发条件</div>
    <ConditionGroupNode
      :disabled="disabled"
      :fields="fields"
      :operators-by-type="operatorsByType"
      :stage="stage"
      :value="group"
      @update:value="onGroupUpdate"
    />
    <div class="bg-muted/50 rounded px-3 py-2 text-sm">
      <div>
        编译预览：
        <code>{{ preview.condition_expr || '恒真（空条件）' }}</code>
      </div>
      <div v-if="preview.errors.length" class="mt-1 text-red-500">
        {{ preview.errors.join('；') }}
      </div>
    </div>
  </div>
</template>
