<script lang="ts" setup>
import type { ActivePlanVersion, PlanItemDetail } from '../../../types/plan';
import type {
  EffectivePlanSegment,
  PlanBindingForm,
  PlanBindingResult,
  RiderResult,
} from '../../../types/rider';

import { computed, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';

import { useAccess } from '@vben/access';
import { VbenButton } from '@vben/common-ui';

import { message } from 'antdv-next';
import dayjs from 'dayjs';

import { useVbenForm } from '#/adapter/form';

import { getPeriodListApi } from '../../../api/period';
import {
  getActivePlanVersionsApi,
  getPlanVersionApi,
} from '../../../api/plan';
import {
  createRiderBindingApi,
  deleteRiderBindingApi,
  getRiderBindingsApi,
  getRiderEffectivePlansApi,
} from '../../../api/rider';
import StatusTag from '../../../components/StatusTag.vue';
import { BINDING_TYPE_OPTIONS } from '../../../constants/enums';
import { summarizeItem } from '../../plan/helpers';
import { bindingFormSchema } from '../data';
import EffectivePlanBar from './EffectivePlanBar.vue';

const props = defineProps<{
  rider: RiderResult;
}>();

const emit = defineEmits<{
  changed: [];
}>();

const router = useRouter();
const { hasAccessByCodes } = useAccess();
const canCalculate = computed(() =>
  hasAccessByCodes(['rs:period:calculate']),
);

const loading = ref(false);
const segmentLoading = ref(false);
const bindings = ref<PlanBindingResult[]>([]);
const segments = ref<EffectivePlanSegment[]>([]);
const versions = ref<ActivePlanVersion[]>([]);
/** plan_version_id → 启用项（含一句话说明） */
const versionItems = ref<Record<number, PlanItemDetail[]>>({});
const expandedKeys = ref<string[]>([]);

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

async function ensureVersionItems(versionIds: number[]) {
  const missing = versionIds.filter((id) => !(id in versionItems.value));
  if (!missing.length) return;
  await Promise.all(
    missing.map(async (id) => {
      try {
        const detail = await getPlanVersionApi(id);
        versionItems.value = {
          ...versionItems.value,
          [id]: (detail?.items ?? []).filter((item) => item.enabled),
        };
      } catch {
        versionItems.value = { ...versionItems.value, [id]: [] };
      }
    }),
  );
}

async function loadBindings() {
  loading.value = true;
  try {
    bindings.value = (await getRiderBindingsApi(props.rider.id)) ?? [];
    const ids = [...new Set(bindings.value.map((row) => row.plan_version_id))];
    await ensureVersionItems(ids);
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
  try {
    versions.value = (await getActivePlanVersionsApi()) ?? [];
  } catch {
    versions.value = [];
  }
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
  message.success('绑定已保存，请到周期算薪页重算');
  formApi.resetForm();
  await reload();
}

async function goCalculatePage() {
  try {
    const res = await getPeriodListApi({
      page: 1,
      site_id: props.rider.site_id,
      size: 50,
    });
    const items = res?.items ?? [];
    const match =
      items.find(
        (row) =>
          row.rider_id === props.rider.id &&
          (row.status === 'open' || row.status === 'reopened'),
      ) ||
      items.find(
        (row) =>
          !row.rider_id && (row.status === 'open' || row.status === 'reopened'),
      ) ||
      items.find((row) => row.rider_id === props.rider.id) ||
      items.find((row) => !row.rider_id);
    if (match) {
      router.push({ path: `/rider-salary/period/${match.id}/calculate` });
      return;
    }
  } catch {
    /* fall through */
  }
  router.push({
    path: '/rider-salary/period',
    query: {
      rider_id: String(props.rider.id),
      site_id: String(props.rider.site_id),
    },
  });
}

async function removeBinding(row: PlanBindingResult) {
  await deleteRiderBindingApi(props.rider.id, row.id);
  message.success('已解除绑定');
  await reload();
}

function itemsOf(versionId: number) {
  return versionItems.value[versionId] ?? [];
}

watch(
  () => props.rider.id,
  () => {
    formApi.resetForm();
    versionItems.value = {};
    expandedKeys.value = [];
    void reload();
  },
);

onMounted(async () => {
  await Promise.all([loadVersions(), reload()]);
});

defineExpose({ reload });
</script>

<template>
  <div class="flex flex-col gap-4" data-testid="rider-binding-timeline">
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
              <div class="min-w-0 flex-1">
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
                <a-collapse
                  v-model:active-key="expandedKeys"
                  :bordered="false"
                  class="mt-2 bg-transparent"
                  ghost
                >
                  <a-collapse-panel
                    :key="String(item.id)"
                    :header="`方案项说明（${itemsOf(item.plan_version_id).length}）`"
                  >
                    <ul
                      v-if="itemsOf(item.plan_version_id).length"
                      class="m-0 list-none space-y-2 p-0"
                    >
                      <li
                        v-for="planItem in itemsOf(item.plan_version_id)"
                        :key="planItem.id"
                        class="text-xs"
                      >
                        <div class="font-medium">{{ planItem.name }}</div>
                        <div class="text-muted-foreground mt-0.5">
                          {{ summarizeItem(planItem) }}
                        </div>
                      </li>
                    </ul>
                    <div v-else class="text-muted-foreground text-xs">暂无启用方案项</div>
                  </a-collapse-panel>
                </a-collapse>
              </div>
              <a-button danger size="small" type="link" @click="removeBinding(item)">
                解除
              </a-button>
            </div>
          </a-timeline-item>
        </a-timeline>
      </div>
    </a-spin>

    <div
      v-access:code="'rs:rider:binding'"
      class="rounded border p-3"
      data-testid="rider-binding-form"
    >
      <div class="mb-2 font-medium">新增绑定</div>
      <Form />
      <div class="mt-2 flex flex-wrap gap-2">
        <a-button type="primary" @click="submit">保存绑定</a-button>
        <VbenButton
          v-if="canCalculate"
          variant="outline"
          data-testid="rider-binding-goto-calculate"
          @click="goCalculatePage"
        >
          去周期算薪页
        </VbenButton>
      </div>
    </div>
  </div>
</template>
