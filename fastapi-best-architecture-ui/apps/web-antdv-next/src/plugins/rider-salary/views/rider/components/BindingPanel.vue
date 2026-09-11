<script lang="ts" setup>
import type { ActivePlanVersion } from '../../../types/plan';
import type {
  EffectivePlanSegment,
  PlanBindingForm,
  PlanBindingResult,
  RiderResult,
} from '../../../types/rider';

import { computed, onMounted, ref, watch } from 'vue';

import { message } from 'antdv-next';
import dayjs from 'dayjs';

import { useVbenForm } from '#/adapter/form';

import { getActivePlanVersionsApi } from '../../../api/plan';
import {
  createRiderBindingApi,
  deleteRiderBindingApi,
  getRiderBindingsApi,
  getRiderEffectivePlansApi,
} from '../../../api/rider';
import StatusTag from '../../../components/StatusTag.vue';
import { BINDING_TYPE_OPTIONS } from '../../../constants/enums';
import { bindingFormSchema } from '../data';
import EffectivePlanBar from './EffectivePlanBar.vue';

const props = defineProps<{
  rider: RiderResult;
}>();

const emit = defineEmits<{
  changed: [];
}>();

const loading = ref(false);
const segmentLoading = ref(false);
const bindings = ref<PlanBindingResult[]>([]);
const segments = ref<EffectivePlanSegment[]>([]);
const versions = ref<ActivePlanVersion[]>([]);

const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  schema: bindingFormSchema,
  showDefaultActions: false,
});

const emptyHint = computed(() =>
  versions.value.length === 0
    ? '暂无启用中的方案版本，请先到薪资方案中启用版本'
    : '请填写下方表单新增绑定',
);

const segmentRange = computed(() => {
  const start = dayjs().subtract(1, 'month').startOf('month').format('YYYY-MM-DD');
  const end = dayjs().add(2, 'month').endOf('month').format('YYYY-MM-DD');
  return { end, start };
});

async function loadBindings() {
  loading.value = true;
  try {
    bindings.value = (await getRiderBindingsApi(props.rider.id)) ?? [];
  } catch {
    bindings.value = [];
  } finally {
    loading.value = false;
  }
}

async function loadSegments() {
  segmentLoading.value = true;
  try {
    segments.value =
      (await getRiderEffectivePlansApi(
        props.rider.id,
        segmentRange.value.start,
        segmentRange.value.end,
      )) ?? [];
  } catch {
    segments.value = [];
  } finally {
    segmentLoading.value = false;
  }
}

async function loadVersions() {
  versions.value = (await getActivePlanVersionsApi()) ?? [];
  const options = versions.value.map((item) => ({
    label: `${item.plan_name} · ${item.short_name} v${item.version_no}`,
    value: item.id,
  }));
  formApi.updateSchema([
    {
      componentProps: {
        notFoundContent: '暂无启用版本',
        options,
        placeholder: options.length ? '请选择启用版本' : '暂无启用版本',
      },
      fieldName: 'plan_version_id',
    },
  ]);
}

async function reload() {
  await Promise.all([loadBindings(), loadSegments()]);
  emit('changed');
}

async function submit() {
  if (versions.value.length === 0) {
    message.warning('暂无启用中的方案版本');
    return;
  }
  const { valid } = await formApi.validate();
  if (!valid) return;
  const values = await formApi.getValues<PlanBindingForm>();
  await createRiderBindingApi(props.rider.id, values);
  message.success('绑定成功');
  formApi.resetForm();
  await reload();
}

async function removeBinding(row: PlanBindingResult) {
  await deleteRiderBindingApi(props.rider.id, row.id);
  message.success('已解除绑定');
  await reload();
}

watch(
  () => props.rider.id,
  () => {
    formApi.resetForm();
    void reload();
  },
);

onMounted(async () => {
  await Promise.all([loadVersions(), reload()]);
});

defineExpose({ reload });
</script>

<template>
  <div class="flex flex-col gap-4">
    <a-alert type="info" show-icon>
      <template #message>当前生效方案（今日）</template>
      <template #description>
        <span v-if="rider.plan_short_name" class="inline-flex items-center gap-2">
          <span
            class="inline-block size-2.5 rounded-full"
            :style="{ background: rider.plan_color || '#1677ff' }"
          ></span>
          {{ rider.plan_short_name }}
          <span v-if="rider.plan_version_id" class="text-muted-foreground text-xs">
            版本 ID {{ rider.plan_version_id }}
          </span>
        </span>
        <span v-else class="text-muted-foreground">今日未绑定方案，下方日历区间将显示空白段</span>
      </template>
    </a-alert>

    <EffectivePlanBar
      :loading="segmentLoading"
      :segments="segments"
      :title="`生效方案预览（${segmentRange.start} ~ ${segmentRange.end}）`"
    />

    <a-spin :spinning="loading">
      <div class="rounded border p-3">
        <div class="mb-2 font-medium">绑定记录</div>
        <a-empty v-if="bindings.length === 0" :description="emptyHint" />
        <a-timeline v-else>
          <a-timeline-item
            v-for="item in bindings"
            :key="item.id"
            :color="item.binding_type === 'override' ? 'orange' : 'blue'"
          >
            <div class="flex items-start justify-between gap-2">
              <div>
                <div class="flex items-center gap-2">
                  <span
                    class="inline-block size-2 rounded-full"
                    :style="{ background: item.plan_color || '#1677ff' }"
                  ></span>
                  <span>{{ item.plan_short_name || `版本 ${item.plan_version_id}` }}</span>
                  <StatusTag :options="BINDING_TYPE_OPTIONS" :value="item.binding_type" />
                </div>
                <div class="text-muted-foreground mt-1 text-xs">
                  {{ item.start_date }} ~ {{ item.end_date || '长期' }}
                </div>
                <div v-if="item.remark" class="mt-1 text-xs">{{ item.remark }}</div>
              </div>
              <a-button danger size="small" type="link" @click="removeBinding(item)">
                解除
              </a-button>
            </div>
          </a-timeline-item>
        </a-timeline>
      </div>
    </a-spin>

    <div v-access:code="'rs:rider:binding'" class="rounded border p-3">
      <div class="mb-2 font-medium">新增绑定</div>
      <Form />
      <a-button class="mt-2" type="primary" @click="submit">保存绑定</a-button>
    </div>
  </div>
</template>
