<script lang="ts" setup>
import type { EmployHistoryForm, EmployHistoryResult, RiderResult } from '../../../types/rider';

import { computed, nextTick, onMounted, ref, watch } from 'vue';

import { confirm, useVbenDrawer } from '@vben/common-ui';

import { message } from 'antdv-next';
import dayjs from 'dayjs';

import { useVbenForm } from '#/adapter/form';

import {
  createRiderEmployHistoryApi,
  deleteRiderEmployHistoryApi,
  getRiderEmployHistoryApi,
  updateRiderEmployHistoryApi,
} from '../../../api/rider';
import StatusTag from '../../../components/StatusTag.vue';
import { EMPLOY_TYPE_OPTIONS, enumLabel } from '../../../constants/enums';
import { employFormSchema } from '../data';
import {
  EMPLOY_WRITE_PERM,
  employRemoveContent,
  toEmployUpdate,
} from '../history-actions';

const props = defineProps<{
  rider: RiderResult;
}>();

const emit = defineEmits<{
  changed: [];
}>();

const loading = ref(false);
const rows = ref<EmployHistoryResult[]>([]);
const editing = ref<EmployHistoryResult>();
const today = dayjs().format('YYYY-MM-DD');

const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  schema: employFormSchema,
  showDefaultActions: false,
});

const [EditForm, editFormApi] = useVbenForm({
  layout: 'vertical',
  schema: employFormSchema,
  showDefaultActions: false,
});

const activeRow = computed(() => {
  const hit = rows.value.find(
    (item) =>
      item.start_date <= today && (!item.end_date || item.end_date >= today),
  );
  return hit ?? rows.value[rows.value.length - 1];
});

const currentSummary = computed(() => {
  if (!activeRow.value) {
    return {
      since: props.rider.hire_date,
      type: props.rider.employ_type,
      typeLabel: enumLabel(EMPLOY_TYPE_OPTIONS, props.rider.employ_type),
    };
  }
  return {
    since: activeRow.value.start_date,
    type: activeRow.value.employ_type,
    typeLabel:
      activeRow.value.employ_type_label ||
      enumLabel(EMPLOY_TYPE_OPTIONS, activeRow.value.employ_type),
  };
});

async function load() {
  loading.value = true;
  try {
    rows.value = (await getRiderEmployHistoryApi(props.rider.id)) ?? [];
  } catch {
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

async function reload() {
  await load();
  emit('changed');
}

async function submit() {
  const { valid } = await formApi.validate();
  if (!valid) return;
  const values = await formApi.getValues<EmployHistoryForm>();
  await createRiderEmployHistoryApi(props.rider.id, values);
  message.success('用工类型已变更；上一段历史会自动收尾，薪资方案需单独绑定。');
  formApi.resetForm();
  await reload();
}

function fillEditForm(row: EmployHistoryResult) {
  editFormApi.setValues({
    employ_type: row.employ_type,
    end_date: row.end_date || undefined,
    remark: row.remark ?? '',
    start_date: row.start_date,
  });
}

function openEdit(row: EmployHistoryResult) {
  editing.value = row;
  editDrawerApi.setData(row).open();
}

async function saveEdit() {
  const row = editing.value;
  if (!row) return;
  const { valid } = await editFormApi.validate();
  if (!valid) return;
  const values = await editFormApi.getValues<EmployHistoryForm>();
  editDrawerApi.lock();
  try {
    await updateRiderEmployHistoryApi(
      props.rider.id,
      row.id,
      toEmployUpdate(values),
    );
    message.success('已保存用工历史，发生变化的日期已标记需重算');
    await editDrawerApi.close();
    await reload();
  } finally {
    editDrawerApi.unlock();
  }
}

async function removeRow(row: EmployHistoryResult) {
  try {
    await confirm({
      content: employRemoveContent({
        ...row,
        employ_type_label:
          row.employ_type_label ||
          enumLabel(EMPLOY_TYPE_OPTIONS, row.employ_type),
      }),
      icon: 'warning',
    });
  } catch {
    return;
  }
  await deleteRiderEmployHistoryApi(props.rider.id, row.id);
  message.success('已删除用工历史，该区间的薪资已标记需重算');
  await reload();
}

const [EditDrawer, editDrawerApi] = useVbenDrawer({
  cancelText: '取消',
  class: 'w-[480px]',
  confirmText: '保存',
  destroyOnClose: true,
  onConfirm: saveEdit,
  onOpenChange(isOpen) {
    if (!isOpen) return;
    const row = editDrawerApi.getData<EmployHistoryResult>() ?? editing.value;
    if (!row) return;
    editing.value = row;
    void nextTick(() => fillEditForm(row));
  },
  title: '编辑用工类型历史',
  zIndex: 1200,
});

watch(
  () => props.rider.id,
  () => {
    formApi.resetForm();
    editDrawerApi.close();
    void reload();
  },
);

onMounted(async () => {
  formApi.setValues({ start_date: today });
  await reload();
});

defineExpose({ reload });
</script>

<template>
  <div class="flex flex-col gap-4">
    <a-alert type="info" show-icon>
      <template #message>当前用工类型</template>
      <template #description>
        <span class="inline-flex items-center gap-2">
          <StatusTag :options="EMPLOY_TYPE_OPTIONS" :value="currentSummary.type" />
          <span>自 {{ currentSummary.since }} 起</span>
        </span>
        <div class="text-muted-foreground mt-1 text-xs">
          列表页「用工类型」列仅显示当前值；完整变更记录见下方时间线。
        </div>
      </template>
    </a-alert>

    <a-spin :spinning="loading">
      <div class="rounded border p-3">
        <div class="mb-2 font-medium">变更历史</div>
        <a-empty v-if="rows.length === 0" description="暂无用工类型历史" />
        <a-timeline v-else>
          <a-timeline-item v-for="item in rows" :key="item.id">
            <div class="flex items-start justify-between gap-2">
              <div>
                <StatusTag :options="EMPLOY_TYPE_OPTIONS" :value="item.employ_type" />
                <div class="text-muted-foreground mt-1 text-xs">
                  {{ item.start_date }} ~ {{ item.end_date || '至今' }}
                </div>
                <div v-if="item.remark" class="mt-1 text-xs">{{ item.remark }}</div>
              </div>
              <div v-access:code="EMPLOY_WRITE_PERM" class="flex shrink-0">
                <a-button size="small" type="link" @click="openEdit(item)">
                  编辑
                </a-button>
                <a-button danger size="small" type="link" @click="removeRow(item)">
                  删除
                </a-button>
              </div>
            </div>
          </a-timeline-item>
        </a-timeline>
      </div>
    </a-spin>

    <div v-access:code="EMPLOY_WRITE_PERM" class="rounded border p-3">
      <div class="mb-1 font-medium">变更用工类型</div>
      <div class="text-muted-foreground mb-3 text-xs">
        填写新生效日期即可（如兼职转全职）；系统会自动将上一段「至今」的记录收尾到前一天。
      </div>
      <Form />
      <a-button class="mt-2" type="primary" @click="submit">保存变更</a-button>
    </div>

    <EditDrawer>
      <a-alert class="mb-3" show-icon type="warning">
        <template #message>保存后，发生变化的日期会标记需重算</template>
        <template #description>
          直接改这一段的类型和日期。与其他历史重叠，或落在已锁账、已发薪周期时，将显示后端返回的错误，本次不会保存。
        </template>
      </a-alert>
      <EditForm />
    </EditDrawer>
  </div>
</template>
