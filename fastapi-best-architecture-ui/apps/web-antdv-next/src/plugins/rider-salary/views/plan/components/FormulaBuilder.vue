<script lang="ts" setup>
import type {
  EngineField,
  EngineFunction,
  EngineValidateResult,
} from '../../../types/engine';
import type { FormulaKind } from '../../../types/plan';

import { computed, onBeforeUnmount, ref, watch } from 'vue';

import { confirm } from '@vben/common-ui';

import { validateEngineApi } from '../../../api/engine';
import { defaultFormula, formulaKindOf } from '../helpers';
import ExpressionBuilder from './ExpressionBuilder.vue';
import LadderEditor from './LadderEditor.vue';

const props = withDefaults(
  defineProps<{
    disabled?: boolean;
    fields: EngineField[];
    functions: EngineFunction[];
    stage: string;
    value?: null | Record<string, unknown>;
  }>(),
  { disabled: false, value: () => ({}) },
);

const emit = defineEmits<{
  'update:value': [value: Record<string, unknown>];
}>();

const kind = computed(() => formulaKindOf(props.value));
const preview = ref<EngineValidateResult>({
  condition_expr: 'True',
  errors: [],
  formula_expr: '0',
  ok: true,
});
const baseSalary = ref(2000);
const guarantee = ref(3000);
let timer: null | ReturnType<typeof setTimeout> = null;

const numberFields = computed(() =>
  props.fields.filter(
    (item) => item.type === 'number' && item.stages.includes(props.stage),
  ),
);

function formula(): Record<string, unknown> {
  return props.value ?? defaultFormula('固定金额');
}

function patch(next: Record<string, unknown>) {
  emit('update:value', next);
}

async function onKindChange(next: string) {
  if (next === kind.value) return;
  if (props.value && Object.keys(props.value).length > 0) {
    try {
      await confirm({
        content: '切换公式类型将清空当前公式，是否继续？',
        icon: 'warning',
      });
    } catch {
      return;
    }
  }
  patch(defaultFormula(next as FormulaKind));
}

function applyBaseSalary() {
  patch({
    类型: '表达式',
    表达式: `${baseSalary.value} * 方案生效天数 / 周期天数`,
  });
}

function applyGuarantee() {
  patch({
    类型: '表达式',
    表达式: `最大值(0, ${guarantee.value} - 本期已计金额)`,
  });
}

async function runValidate() {
  try {
    preview.value = await validateEngineApi({
      condition_json: {},
      formula_json: formula(),
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
  [() => props.value, () => props.stage],
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
  <div class="flex flex-col gap-3">
    <div class="text-sm font-medium">计算公式</div>
    <a-radio-group
      :disabled="disabled"
      :value="kind"
      button-style="solid"
      @update:value="(v) => onKindChange(String(v ?? ''))"
    >
      <a-radio-button value="固定金额">固定金额</a-radio-button>
      <a-radio-button value="字段乘单价">字段乘单价</a-radio-button>
      <a-radio-button value="阶梯">阶梯</a-radio-button>
      <a-radio-button value="表达式">表达式</a-radio-button>
    </a-radio-group>

    <div v-if="kind === '固定金额'" class="flex flex-col gap-2">
      <div class="text-muted-foreground text-xs">
        每命中一次加该金额，符号由科目方向决定
      </div>
      <a-input-number
        :disabled="disabled"
        :precision="2"
        :value="formula().金额 as number"
        class="w-[200px]"
        placeholder="金额"
        @update:value="(v) => patch({ 类型: '固定金额', 金额: v })"
      />
    </div>

    <div v-else-if="kind === '字段乘单价'" class="flex flex-wrap gap-3">
      <div>
        <div class="mb-1 text-xs">字段</div>
        <a-select
          :disabled="disabled"
          :options="numberFields.map((item) => ({ label: item.name, value: item.name }))"
          :value="formula().字段"
          class="min-w-[160px]"
          @update:value="(v) => patch({ ...formula(), 字段: String(v ?? '') })"
        />
      </div>
      <div>
        <div class="mb-1 text-xs">单价</div>
        <a-input-number
          :disabled="disabled"
          :precision="4"
          :value="formula().单价 as number"
          @update:value="(v) => patch({ ...formula(), 单价: v })"
        />
      </div>
      <div>
        <div class="mb-1 text-xs">起算值</div>
        <a-input-number
          :disabled="disabled"
          :value="(formula().起算值 as number) ?? 0"
          @update:value="(v) => patch({ ...formula(), 起算值: v })"
        />
      </div>
      <div class="text-muted-foreground w-full text-xs">
        金额 = max(0, (字段 − 起算值) × 单价)
      </div>
    </div>

    <LadderEditor
      v-else-if="kind === '阶梯'"
      :disabled="disabled"
      :fields="fields"
      :stage="stage"
      :value="formula()"
      @update:value="patch"
    />

    <div v-else class="flex flex-col gap-3">
      <div class="flex flex-wrap items-end gap-2">
        <div>
          <div class="mb-1 text-xs">底薪金额</div>
          <a-input-number v-model:value="baseSalary" :disabled="disabled" :precision="2" />
        </div>
        <a-button :disabled="disabled" @click="applyBaseSalary">底薪分摊</a-button>
        <div>
          <div class="mb-1 text-xs">保底金额</div>
          <a-input-number v-model:value="guarantee" :disabled="disabled" :precision="2" />
        </div>
        <a-button :disabled="disabled" @click="applyGuarantee">保底</a-button>
      </div>
      <ExpressionBuilder
        :disabled="disabled"
        :fields="fields"
        :functions="functions"
        :stage="stage"
        :value="String(formula().表达式 || '')"
        @update:value="(v) => patch({ 类型: '表达式', 表达式: v })"
      />
    </div>

    <div class="bg-muted/50 rounded px-3 py-2 text-sm">
      <div>
        编译预览：
        <code>{{ preview.formula_expr }}</code>
      </div>
      <div v-if="preview.errors.length" class="mt-1 text-red-500">
        {{ preview.errors.join('；') }}
      </div>
    </div>
  </div>
</template>
