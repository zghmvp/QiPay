<script lang="ts" setup>
import type { EngineField } from '../../../types/engine';
import type { ConditionGroup, ConditionLeaf } from '../../../types/plan';

import { computed } from 'vue';

import { IconifyIcon } from '@vben/icons';

import { message } from 'antdv-next';

import {
  defaultOperatorForType,
  defaultValueFor,
  emptyGroup,
  FIELD_GROUPS,
  isGroup,
  MULTI_OPERATORS,
  OPERATORS_BY_TYPE,
  RANGE_OPERATORS,
} from '../helpers';

defineOptions({ name: 'ConditionGroupNode' });

const props = withDefaults(
  defineProps<{
    depth?: number;
    disabled?: boolean;
    fields: EngineField[];
    operatorsByType?: Record<string, string[]>;
    stage: string;
    value: ConditionGroup;
  }>(),
  { depth: 1, disabled: false, operatorsByType: () => ({}) },
);

const emit = defineEmits<{
  'update:value': [value: ConditionGroup];
}>();

const availableFields = computed(() =>
  props.fields.filter((item) => item.stages.includes(props.stage)),
);

const fieldOptions = computed(() =>
  FIELD_GROUPS.map((group) => ({
    label: group.label,
    options: availableFields.value
      .filter((item) => group.names.includes(item.name))
      .map((item) => ({
        label: item.unit ? `${item.name}（${item.unit}）` : item.name,
        value: item.name,
      })),
  })).filter((group) => group.options.length > 0),
);

function fieldOf(name?: string) {
  return availableFields.value.find((item) => item.name === name);
}

function operatorsOf(name?: string) {
  const spec = fieldOf(name);
  const fromApi = spec ? props.operatorsByType[spec.type] : undefined;
  if (fromApi?.length) return fromApi;
  return OPERATORS_BY_TYPE[spec?.type || 'number'] ?? ['='];
}

function patch(next: ConditionGroup) {
  emit('update:value', next);
}

function setLogic(logic: ConditionGroup['逻辑']) {
  const next: ConditionGroup = { ...props.value, 逻辑: logic };
  if (logic === '非' && next.条件.length > 1) {
    next.条件 = next.条件.slice(0, 1);
  }
  patch(next);
}

function addLeaf() {
  if (props.value.逻辑 === '非' && props.value.条件.length >= 1) {
    message.warning('「非」组只能有一个子条件');
    return;
  }
  const first = availableFields.value[0];
  const operator = defaultOperatorForType(first?.type);
  patch({
    ...props.value,
    条件: [
      ...props.value.条件,
      {
        值: defaultValueFor(first?.type, operator),
        字段: first?.name,
        运算符: operator,
      },
    ],
  });
}

function addGroup() {
  if (props.depth >= 2) {
    message.warning('条件最多嵌套 2 层');
    return;
  }
  if (props.value.逻辑 === '非' && props.value.条件.length >= 1) {
    message.warning('「非」组只能有一个子条件');
    return;
  }
  patch({
    ...props.value,
    条件: [...props.value.条件, emptyGroup('或')],
  });
}

function removeAt(index: number) {
  patch({
    ...props.value,
    条件: props.value.条件.filter((_, i) => i !== index),
  });
}

function updateLeaf(index: number, leaf: ConditionLeaf) {
  const 条件 = [...props.value.条件];
  条件[index] = leaf;
  patch({ ...props.value, 条件 });
}

function updateGroup(index: number, group: ConditionGroup) {
  const 条件 = [...props.value.条件];
  条件[index] = group;
  patch({ ...props.value, 条件 });
}

function onFieldChange(index: number, name: string) {
  const spec = fieldOf(name);
  const operator = defaultOperatorForType(spec?.type);
  updateLeaf(index, {
    值: defaultValueFor(spec?.type, operator),
    字段: name,
    运算符: operator,
  });
}

function onOperatorChange(index: number, leaf: ConditionLeaf, operator: string) {
  const spec = fieldOf(leaf.字段);
  updateLeaf(index, {
    ...leaf,
    值: defaultValueFor(spec?.type, operator),
    运算符: operator,
  });
}

function rangeTuple(value: unknown): [unknown, unknown] {
  if (Array.isArray(value) && value.length >= 2) return [value[0], value[1]];
  return [undefined, undefined];
}

function setRange(index: number, leaf: ConditionLeaf, pos: 0 | 1, val: unknown) {
  const tuple = rangeTuple(leaf.值);
  tuple[pos] = val;
  updateLeaf(index, { ...leaf, 值: tuple });
}
</script>

<template>
  <div class="rounded border border-border p-3">
    <div class="mb-3 flex flex-wrap items-center gap-2">
      <a-segmented
        :disabled="disabled"
        :options="[
          { label: '且', value: '且' },
          { label: '或', value: '或' },
          { label: '非', value: '非' },
        ]"
        :value="value.逻辑"
        @update:value="(v) => setLogic(String(v) as ConditionGroup['逻辑'])"
      />
      <a-button :disabled="disabled" size="small" @click="addLeaf">
        添加条件
      </a-button>
      <a-tooltip :title="depth >= 2 ? '条件最多嵌套 2 层' : ''">
        <a-button
          :disabled="disabled || depth >= 2"
          size="small"
          @click="addGroup"
        >
          添加条件组
        </a-button>
      </a-tooltip>
      <a-button
        v-if="depth === 1"
        :disabled="disabled"
        size="small"
        @click="patch(emptyGroup())"
      >
        清空
      </a-button>
    </div>
    <div v-if="value.条件.length === 0" class="text-muted-foreground text-sm">
      空条件视为恒真
    </div>
    <div class="flex flex-col gap-2">
      <template v-for="(node, index) in value.条件" :key="index">
        <div
          v-if="isGroup(node)"
          class="bg-muted/40 rounded border border-dashed p-2"
        >
          <div class="mb-2 flex justify-end">
            <a-button
              :disabled="disabled"
              size="small"
              type="link"
              danger
              @click="removeAt(index)"
            >
              删除组
            </a-button>
          </div>
          <ConditionGroupNode
            :depth="depth + 1"
            :disabled="disabled"
            :fields="fields"
            :operators-by-type="operatorsByType"
            :stage="stage"
            :value="node"
            @update:value="(v) => updateGroup(index, v)"
          />
        </div>
        <div v-else class="flex flex-wrap items-start gap-2">
          <a-select
            :disabled="disabled"
            :options="fieldOptions"
            :value="node.字段"
            class="min-w-[160px]"
            placeholder="字段"
            show-search
            option-filter-prop="label"
            @update:value="(v) => onFieldChange(index, String(v ?? ''))"
          />
          <a-select
            :disabled="disabled"
            :options="operatorsOf(node.字段).map((op) => ({ label: op, value: op }))"
            :value="node.运算符"
            class="min-w-[110px]"
            placeholder="运算符"
            @update:value="(v) => onOperatorChange(index, node, String(v ?? ''))"
          />
          <template v-if="RANGE_OPERATORS.has(node.运算符 || '')">
            <template v-if="fieldOf(node.字段)?.type === 'time'">
              <a-time-picker
                :disabled="disabled"
                :value="rangeTuple(node.值)[0] as string"
                class="w-[110px]"
                format="HH:mm"
                placeholder="开始"
                value-format="HH:mm"
                @update:value="(v) => setRange(index, node, 0, v)"
              />
              <a-time-picker
                :disabled="disabled"
                :value="rangeTuple(node.值)[1] as string"
                class="w-[110px]"
                format="HH:mm"
                placeholder="结束"
                value-format="HH:mm"
                @update:value="(v) => setRange(index, node, 1, v)"
              />
            </template>
            <template v-else-if="fieldOf(node.字段)?.type === 'date'">
              <a-date-picker
                :disabled="disabled"
                :value="rangeTuple(node.值)[0] as string"
                class="w-[130px]"
                placeholder="下限"
                value-format="YYYY-MM-DD"
                @update:value="(v) => setRange(index, node, 0, v)"
              />
              <a-date-picker
                :disabled="disabled"
                :value="rangeTuple(node.值)[1] as string"
                class="w-[130px]"
                placeholder="上限"
                value-format="YYYY-MM-DD"
                @update:value="(v) => setRange(index, node, 1, v)"
              />
            </template>
            <template v-else>
              <a-input-number
                :disabled="disabled"
                :value="rangeTuple(node.值)[0] as number"
                class="w-[110px]"
                placeholder="下限"
                @update:value="(v) => setRange(index, node, 0, v)"
              />
              <a-input-number
                :disabled="disabled"
                :value="rangeTuple(node.值)[1] as number"
                class="w-[110px]"
                placeholder="上限"
                @update:value="(v) => setRange(index, node, 1, v)"
              />
              <span class="text-muted-foreground text-xs">区间含两端</span>
            </template>
          </template>
          <a-select
            v-else-if="fieldOf(node.字段)?.type === 'enum'"
            :disabled="disabled"
            :mode="MULTI_OPERATORS.has(node.运算符 || '') ? 'multiple' : undefined"
            :options="fieldOf(node.字段)?.enum_options ?? []"
            :value="node.值 as never"
            class="min-w-[140px]"
            placeholder="值"
            @update:value="(v) => updateLeaf(index, { ...node, 值: v })"
          />
          <a-switch
            v-else-if="fieldOf(node.字段)?.type === 'bool'"
            :checked="Boolean(node.值)"
            :disabled="disabled"
            checked-children="是"
            un-checked-children="否"
            @update:checked="(v) => updateLeaf(index, { ...node, 值: Boolean(v) })"
          />
          <a-date-picker
            v-else-if="fieldOf(node.字段)?.type === 'date'"
            :disabled="disabled"
            :value="node.值 as string"
            value-format="YYYY-MM-DD"
            @update:value="(v) => updateLeaf(index, { ...node, 值: v })"
          />
          <a-time-picker
            v-else-if="fieldOf(node.字段)?.type === 'time'"
            :disabled="disabled"
            :value="node.值 as string"
            format="HH:mm"
            value-format="HH:mm"
            @update:value="(v) => updateLeaf(index, { ...node, 值: v })"
          />
          <a-input-number
            v-else
            :disabled="disabled"
            :value="node.值 as number"
            class="w-[120px]"
            placeholder="值"
            @update:value="(v) => updateLeaf(index, { ...node, 值: v })"
          />
          <a-button
            :disabled="disabled"
            size="small"
            type="text"
            danger
            @click="removeAt(index)"
          >
            <IconifyIcon class="size-4" icon="lucide:trash-2" />
          </a-button>
        </div>
      </template>
    </div>
  </div>
</template>
