<script lang="ts" setup>
import type { EngineField, EngineFunction } from '../../types/engine';
import type { PlanItemDraft, PlanVersionDetail } from '../../types/plan';
import type { SubjectResult } from '../../types/subject';

import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { confirm, useVbenDrawer, useVbenModal, VbenButton } from '@vben/common-ui';

import { message } from 'antdv-next';

import { buildItemsFromPreset } from '../../constants/plan-presets';
import type { PlanPreset } from '../../constants/plan-presets';
import type { PlanPresetApplyMode } from './components/PlanPresetPicker.vue';

import { getEngineFieldsApi, getEngineFunctionsApi, getEngineOperatorsApi } from '../../api/engine';
import {
  activatePlanVersionApi,
  getPlanVersionApi,
  putPlanVersionItemsApi,
  updatePlanVersionApi,
} from '../../api/plan';
import { getAllSubjectsApi } from '../../api/subject';
import SubjectSelect from '../../components/SubjectSelect.vue';
import {
  CALC_STAGE_OPTIONS,
  enumTagOptions,
  PLAN_MODE_TAG_OPTIONS,
} from '../../constants/enums';
import PageContainer from '../_shared/PageContainer.vue';
import ConditionBuilder from './components/ConditionBuilder.vue';
import FormulaBuilder from './components/FormulaBuilder.vue';
import PlanItemTable from './components/PlanItemTable.vue';
import RollbackModal from './components/RollbackModal.vue';
import PlanPresetPicker from './components/PlanPresetPicker.vue';
import TrialPanel from './components/TrialPanel.vue';
import VersionStatusTag from './components/VersionStatusTag.vue';
import {
  activateHint,
  canEditVersion,
  findMisplacedGuaranteeKeys,
  sinkGuaranteeItems,
  toDraftItems,
  toSaveItems,
  trialLabel,
} from './helpers';

const route = useRoute();
const router = useRouter();

const loading = ref(false);
const saving = ref(false);
const version = ref<PlanVersionDetail>();
const items = ref<PlanItemDraft[]>([]);
const selectedKey = ref('');
const snapshot = ref('');
const fields = ref<EngineField[]>([]);
const functions = ref<EngineFunction[]>([]);
const operatorsByType = ref<Record<string, string[]>>({});
const subjects = ref<SubjectResult[]>([]);

const versionId = computed(() => Number(route.params.versionId));
const readonly = computed(
  () => !canEditVersion(version.value?.status, version.value?.is_used),
);
const selected = computed(
  () => items.value.find((item) => item._key === selectedKey.value),
);
const dirty = computed(() => JSON.stringify(toSaveItems(items.value)) !== snapshot.value);
const trial = computed(() =>
  trialLabel({
    dirty: dirty.value,
    itemsHash: version.value?.items_hash,
    trialHash: version.value?.trial_hash,
    trialPassed: version.value?.trial_passed,
  }),
);
const enableHint = computed(() =>
  activateHint({
    dirty: dirty.value,
    itemsHash: version.value?.items_hash,
    trialHash: version.value?.trial_hash,
    trialPassed: version.value?.trial_passed,
  }),
);

const [TrialDrawer, trialApi] = useVbenDrawer({ connectedComponent: TrialPanel });
const [RollbackComp, rollbackApi] = useVbenModal({ connectedComponent: RollbackModal });
const [PresetPicker, presetApi] = useVbenModal({ connectedComponent: PlanPresetPicker });

function subjectNameOf(id?: number) {
  return subjects.value.find((item) => item.id === id)?.name || '未选科目';
}

function patchSelected(partial: Partial<PlanItemDraft>) {
  items.value = items.value.map((item) =>
    item._key === selectedKey.value ? { ...item, ...partial } : item,
  );
}

async function loadMeta() {
  const [fieldList, fnList, opRes, subjectList] = await Promise.all([
    getEngineFieldsApi(),
    getEngineFunctionsApi(),
    getEngineOperatorsApi(),
    getAllSubjectsApi(),
  ]);
  fields.value = fieldList ?? [];
  functions.value = fnList ?? [];
  subjects.value = subjectList ?? [];
  if (opRes && !('operators' in opRes)) {
    operatorsByType.value = opRes as Record<string, string[]>;
  }
}

async function loadVersion() {
  if (!versionId.value) return;
  loading.value = true;
  try {
    const data = await getPlanVersionApi(versionId.value);
    version.value = data;
    items.value = toDraftItems(data.items ?? []);
    snapshot.value = JSON.stringify(toSaveItems(items.value));
    selectedKey.value = items.value[0]?._key ?? '';
  } finally {
    loading.value = false;
  }
}

async function saveItems() {
  const pk = versionId.value;
  if (!pk || readonly.value) return;
  const payload = toSaveItems(items.value);
  if (payload.some((item) => !item.subject_id || !item.name.trim())) {
    message.warning('请完善每一项的名称与科目');
    return;
  }
  const misplaced = findMisplacedGuaranteeKeys(items.value);
  if (misplaced.length > 0) {
    try {
      await confirm({
        content:
          '保底项应放在周期阶段最后执行，否则「本期已计金额」尚未包含后续项，补差可能错误。点击确定将自动沉底后再保存；取消则按当前顺序保存（不强制拦截）。',
        icon: 'warning',
      });
      items.value = sinkGuaranteeItems(items.value);
    } catch {
      // 取消=不沉底仍保存（弱提示）
    }
  }
  saving.value = true;
  try {
    if (version.value?.mode_tag) {
      await updatePlanVersionApi(pk, { mode_tag: version.value.mode_tag });
    }
    const data = await putPlanVersionItemsApi(pk, toSaveItems(items.value));
    version.value = data;
    items.value = toDraftItems(data.items ?? []);
    snapshot.value = JSON.stringify(toSaveItems(items.value));
    selectedKey.value = items.value[0]?._key ?? selectedKey.value;
    message.success('方案项已保存，需重新试算后再启用');
  } finally {
    saving.value = false;
  }
}

function openTrial() {
  trialApi
    .setData({
      onSuccess: loadVersion,
      versionId: versionId.value,
    })
    .open();
}

async function activate() {
  if (enableHint.value) {
    message.warning(enableHint.value);
    return;
  }
  try {
    await confirm({ content: '确认启用该方案版本？启用后内容不可再改。', icon: 'warning' });
  } catch {
    return;
  }
  await activatePlanVersionApi(versionId.value);
  message.success('已启用');
  await loadVersion();
}

function openPresetPicker() {
  presetApi
    .setData({
      defaultMode: items.value.length > 0 ? 'replace' : 'replace',
      onApply: (preset: PlanPreset, mode: PlanPresetApplyMode) => {
        void applyPreset(preset, mode);
      },
    })
    .open();
}

async function applyPreset(preset: PlanPreset, mode: PlanPresetApplyMode) {
  if (readonly.value) return;
  if (items.value.length > 0 && mode === 'replace') {
    try {
      await confirm({
        content: `将用案例「${preset.name}」替换当前全部 ${items.value.length} 条方案项，是否继续？`,
        icon: 'warning',
      });
    } catch {
      return;
    }
  }
  try {
    const built = buildItemsFromPreset(preset, subjects.value);
    if (version.value) version.value.mode_tag = preset.mode_tag;
    items.value = mode === 'append' ? [...items.value, ...built] : built;
    selectedKey.value = built[0]?._key ?? items.value[0]?._key ?? '';
    message.success(`已导入案例「${preset.name}」${mode === 'append' ? '（追加）' : ''}`);
  } catch (error) {
    message.error(error instanceof Error ? error.message : '导入失败');
  }
}

onMounted(async () => {
  await loadMeta();
  await loadVersion();
});

watch(versionId, () => {
  loadVersion();
});
</script>

<template>
  <PageContainer>
    <a-spin class="min-h-0 flex-1" :spinning="loading" wrapper-class-name="h-full">
      <div class="flex h-full min-h-0 flex-col gap-3">
        <div class="flex flex-wrap items-center gap-3 rounded border px-4 py-3">
          <span class="text-lg font-medium">
            {{ version?.plan?.name || '方案' }} / v{{ version?.version_no }}
          </span>
          <VersionStatusTag :value="version?.status" />
          <a-select
            :disabled="readonly"
            :options="enumTagOptions(PLAN_MODE_TAG_OPTIONS)"
            :value="version?.mode_tag"
            class="w-[160px]"
            @update:value="(v) => version && (version.mode_tag = String(v ?? ''))"
          />
          <a-tag :color="version?.is_used ? 'orange' : 'default'">
            {{ version?.is_used ? '已被使用' : '未使用' }}
          </a-tag>
          <a-tag :color="trial.color">{{ trial.text }}</a-tag>
          <span v-if="readonly" class="text-muted-foreground text-sm">
            已使用或非草稿版本只读，请停用后复制为新版本再改
          </span>
        </div>

        <div class="grid min-h-0 flex-1 grid-cols-1 gap-3 xl:grid-cols-12">
          <div class="overflow-auto xl:col-span-5">
            <PlanItemTable
              :disabled="readonly"
              :items="items"
              :selected-key="selectedKey"
              :subject-name-of="subjectNameOf"
              @select="(key) => (selectedKey = key)"
              @update:items="(next) => (items = next)"
            />
          </div>
          <div class="overflow-auto rounded border p-4 xl:col-span-7">
            <a-empty v-if="!selected" description="请选择或添加方案项" />
            <div v-else class="flex flex-col gap-4">
              <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div>
                  <div class="mb-1 text-sm">名称</div>
                  <a-input
                    :disabled="readonly"
                    :value="selected.name"
                    @update:value="(v) => patchSelected({ name: String(v ?? '') })"
                  />
                </div>
                <div>
                  <div class="mb-1 text-sm">科目</div>
                  <SubjectSelect
                    :disabled="readonly"
                    :value="selected.subject_id || undefined"
                    @update:value="(v) => patchSelected({ subject_id: Number(v || 0) })"
                  />
                </div>
                <div>
                  <div class="mb-1 text-sm">计算阶段</div>
                  <a-select
                    :disabled="readonly"
                    :options="enumTagOptions(CALC_STAGE_OPTIONS)"
                    :value="selected.stage"
                    class="w-full"
                    @update:value="(v) => patchSelected({ stage: String(v ?? '') })"
                  />
                </div>
                <div>
                  <div class="mb-1 text-sm">备注（作一句话说明优先展示）</div>
                  <a-input
                    :disabled="readonly"
                    placeholder="选填；有备注则绑定/骑手端优先显示备注"
                    :value="selected.remark ?? ''"
                    @update:value="(v) => patchSelected({ remark: String(v ?? '') })"
                  />
                </div>
              </div>
              <ConditionBuilder
                :disabled="readonly"
                :fields="fields"
                :operators-by-type="operatorsByType"
                :stage="selected.stage"
                :value="selected.condition_json"
                @update:value="(v) => patchSelected({ condition_json: v })"
              />
              <FormulaBuilder
                :disabled="readonly"
                :fields="fields"
                :functions="functions"
                :stage="selected.stage"
                :value="selected.formula_json"
                @update:value="(v) => patchSelected({ formula_json: v })"
              />
            </div>
          </div>
        </div>

        <div class="flex flex-wrap items-center gap-2 border-t pt-3">
          <VbenButton
            v-access:code="'rs:plan:edit'"
            :disabled="readonly"
            variant="outline"
            @click="openPresetPicker"
          >
            从案例导入
          </VbenButton>
          <VbenButton
            v-access:code="'rs:plan:edit'"
            :disabled="readonly"
            :loading="saving"
            @click="saveItems"
          >
            保存方案项
          </VbenButton>
          <VbenButton v-access:code="'rs:plan:trial'" @click="openTrial">试算</VbenButton>
          <a-tooltip :title="enableHint || '启用后不可再编辑该版本'">
            <span>
              <VbenButton
                v-access:code="'rs:plan:activate'"
                :disabled="readonly || Boolean(enableHint)"
                @click="activate"
              >
                启用
              </VbenButton>
            </span>
          </a-tooltip>
          <a-button
            v-access:code="'rs:plan:rollback'"
            danger
            :disabled="version?.status === 'draft'"
            @click="
              rollbackApi
                .setData({
                  onSuccess: (id?: number) =>
                    id
                      ? router.push(`/rider-salary/plan/editor/${id}`)
                      : loadVersion(),
                  planId: version?.plan_id,
                  versionId,
                })
                .open()
            "
          >
            回退
          </a-button>
          <a-button @click="router.push('/rider-salary/plan')">返回</a-button>
        </div>
      </div>
    </a-spin>
    <TrialDrawer />
    <RollbackComp />
    <PresetPicker />
  </PageContainer>
</template>
