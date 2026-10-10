<script lang="ts" setup>
import type { EngineField, EngineFormulaTemplate, EngineFunction } from '../../types/engine';
import type { PlanItemDraft, PlanItemParam, PlanVersionDetail } from '../../types/plan';
import type { SubjectResult } from '../../types/subject';

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router';

import { confirm, useVbenDrawer, useVbenModal, VbenButton } from '@vben/common-ui';

import { message } from 'antdv-next';

import { buildItemsFromPreset } from '../../constants/plan-presets';
import type { PlanPreset } from '../../constants/plan-presets';
import type { PlanPresetApplyMode } from './components/PlanPresetPicker.vue';

import {
  getEngineFieldsApi,
  getEngineFunctionsApi,
  getEngineOperatorsApi,
  getFormulaTemplatesApi,
} from '../../api/engine';
import {
  activatePlanVersionApi,
  createPlanVersionApi,
  getPlanApi,
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
  accruedSortHint,
  activateHint,
  canEditVersion,
  emptyPlanItemsHash,
  ILLEGAL_LADDER_MESSAGE,
  isIllegalLadderFormula,
  isPlanItemsDirty,
  moveAccruedItemsLast,
  planEditorVersionId,
  planItemsHash,
  readUnsavedPlanDraft,
  shouldTrialWithoutSaving,
  toDraftItems,
  toSaveItems,
  trialLabel,
  UNSAVED_PLAN_LEAVE_MESSAGE,
  unreplacedPlaceholderLabels,
} from './helpers';

const route = useRoute();
const router = useRouter();

const loading = ref(false);
const saving = ref(false);
const version = ref<PlanVersionDetail>();
const planName = ref('');
const modeTag = ref('custom');
const items = ref<PlanItemDraft[]>([]);
const selectedKey = ref('');
const savedItemsHash = ref(emptyPlanItemsHash());
const fields = ref<EngineField[]>([]);
const functions = ref<EngineFunction[]>([]);
const templates = ref<EngineFormulaTemplate[]>([]);
const operatorsByType = ref<Record<string, string[]>>({});
const subjects = ref<SubjectResult[]>([]);

const versionId = computed(() => planEditorVersionId(route.params.versionId));
const isNew = computed(() => versionId.value <= 0);
const readonly = computed(
  () => !isNew.value && !canEditVersion(version.value?.status, version.value?.is_used),
);
const selected = computed(
  () => items.value.find((item) => item._key === selectedKey.value),
);
const dirty = computed(
  () => !readonly.value && isPlanItemsDirty(items.value, savedItemsHash.value),
);
const trial = computed(() =>
  trialLabel({
    dirty: dirty.value,
    itemsHash: version.value?.items_hash,
    trialHash: version.value?.trial_hash,
    trialPassed: version.value?.trial_passed,
  }),
);
const enableHint = computed(() => {
  if (isNew.value) return '请先保存方案项';
  return activateHint({
    dirty: dirty.value,
    itemsHash: version.value?.items_hash,
    trialHash: version.value?.trial_hash,
    trialPassed: version.value?.trial_passed,
  });
});
const trialHint = computed(() =>
  shouldTrialWithoutSaving(versionId.value, dirty.value)
    ? '按当前未保存内容试算，不会写入方案版本'
    : '',
);
const accruedHint = computed(() =>
  readonly.value ? '' : accruedSortHint(items.value),
);

const [TrialDrawer, trialApi] = useVbenDrawer({ connectedComponent: TrialPanel });
const [RollbackComp, rollbackApi] = useVbenModal({ connectedComponent: RollbackModal });
const [PresetPicker, presetApi] = useVbenModal({ connectedComponent: PlanPresetPicker });

function setModeTag(value: unknown) {
  modeTag.value = String(value ?? 'custom');
  if (version.value) version.value.mode_tag = modeTag.value;
}

function queryPlanId() {
  const raw = route.query.plan_id;
  const text = Array.isArray(raw) ? raw[0] : raw;
  const id = Number(text);
  return Number.isInteger(id) && id > 0 ? id : 0;
}

function subjectNameOf(id?: number) {
  return subjects.value.find((item) => item.id === id)?.name || '未选科目';
}

function readyItems(purpose: 'save' | 'trial'): PlanItemParam[] | undefined {
  const payload = toSaveItems(items.value);
  if (!payload.length) {
    message.warning(purpose === 'trial' ? '请先配置方案项再试算' : '请先配置方案项');
    return;
  }
  if (payload.some((item) => !item.subject_id || !item.name.trim())) {
    message.warning('请完善每一项的名称与科目');
    return;
  }
  const illegal = payload.find((item) => isIllegalLadderFormula(item.formula_json));
  if (illegal) {
    message.warning(`「${illegal.name}」${ILLEGAL_LADDER_MESSAGE}`);
    return;
  }
  const pending = [
    ...new Set(payload.flatMap((item) => unreplacedPlaceholderLabels(item.formula_json, templates.value))),
  ];
  if (pending.length) {
    message.warning(`请先替换占位符「${pending.join('」「')}」`);
    return;
  }
  if (accruedHint.value) {
    message.warning(accruedHint.value);
    return;
  }
  return payload;
}

function patchSelected(partial: Partial<PlanItemDraft>) {
  items.value = items.value.map((item) =>
    item._key === selectedKey.value ? { ...item, ...partial } : item,
  );
}

async function loadMeta() {
  const [fieldList, fnList, opRes, subjectList, templateList] = await Promise.all([
    getEngineFieldsApi(),
    getEngineFunctionsApi(),
    getEngineOperatorsApi(),
    getAllSubjectsApi(),
    getFormulaTemplatesApi(),
  ]);
  fields.value = fieldList ?? [];
  functions.value = fnList ?? [];
  templates.value = templateList ?? [];
  subjects.value = subjectList ?? [];
  if (opRes && !('operators' in opRes)) {
    operatorsByType.value = opRes as Record<string, string[]>;
  }
}

async function loadNewDraft() {
  const draft = readUnsavedPlanDraft(history.state);
  modeTag.value = draft.modeTag || 'custom';
  items.value = toDraftItems(draft.draftItems ?? []);
  savedItemsHash.value = emptyPlanItemsHash();
  selectedKey.value = items.value[0]?._key ?? '';
  version.value = undefined;
  const planId = queryPlanId();
  planName.value = '';
  if (!planId) return;
  const plan = await getPlanApi(planId);
  planName.value = plan?.name || '';
}

async function loadVersion() {
  loading.value = true;
  try {
    if (!versionId.value) {
      await loadNewDraft();
      return;
    }
    const data = await getPlanVersionApi(versionId.value);
    version.value = data;
    modeTag.value = data.mode_tag || 'custom';
    planName.value = data.plan?.name || '';
    items.value = toDraftItems(data.items ?? []);
    savedItemsHash.value = data.items_hash || planItemsHash(items.value);
    selectedKey.value = items.value[0]?._key ?? '';
  } finally {
    loading.value = false;
  }
}

async function saveItems() {
  if (readonly.value) return;
  const payload = readyItems('save');
  if (!payload) return;
  saving.value = true;
  try {
    let pk = versionId.value;
    if (!pk) {
      const planId = queryPlanId();
      if (!planId) {
        message.warning('请从方案列表进入新建');
        return;
      }
      const created = await createPlanVersionApi({
        mode_tag: modeTag.value,
        plan_id: planId,
      });
      pk = created.id;
    } else if (modeTag.value) {
      await updatePlanVersionApi(pk, { mode_tag: modeTag.value });
    }
    const data = await putPlanVersionItemsApi(pk, payload);
    message.success('方案项已保存，需重新试算后再启用');
    savedItemsHash.value = data.items_hash || planItemsHash(toDraftItems(payload));
    if (isNew.value) {
      await router.replace(`/rider-salary/plan/editor/${pk}`);
      return;
    }
    version.value = data;
    modeTag.value = data.mode_tag || modeTag.value;
    items.value = toDraftItems(data.items ?? []);
    savedItemsHash.value = data.items_hash || planItemsHash(items.value);
    selectedKey.value = items.value[0]?._key ?? selectedKey.value;
  } finally {
    saving.value = false;
  }
}

function openTrial() {
  const unsaved = shouldTrialWithoutSaving(versionId.value, dirty.value);
  if (!unsaved) {
    trialApi
      .setData({
        onSuccess: loadVersion,
        unsaved: false,
        versionId: versionId.value,
      })
      .open();
    return;
  }
  const payload = readyItems('trial');
  if (!payload) return;
  trialApi
    .setData({
      items: payload,
      unsaved: true,
    })
    .open();
}

function moveAccruedLast() {
  items.value = moveAccruedItemsLast(items.value);
  if (accruedSortHint(items.value)) {
    message.warning('仍有多项引用「本期已计金额」，只能有一项排在周期阶段最后');
    return;
  }
  message.success('已把保底项移到周期阶段最后');
}

async function activate() {
  if (accruedHint.value) {
    message.warning(accruedHint.value);
    return;
  }
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
    modeTag.value = preset.mode_tag;
    if (version.value) version.value.mode_tag = preset.mode_tag;
    items.value = mode === 'append' ? [...items.value, ...built] : built;
    selectedKey.value = built[0]?._key ?? items.value[0]?._key ?? '';
    message.success(`已导入案例「${preset.name}」${mode === 'append' ? '（追加）' : ''}`);
  } catch (error) {
    message.error(error instanceof Error ? error.message : '导入失败');
  }
}

function onBeforeUnload(event: BeforeUnloadEvent) {
  if (!dirty.value) return;
  event.preventDefault();
  event.returnValue = UNSAVED_PLAN_LEAVE_MESSAGE;
}

onBeforeRouteLeave(async () => {
  if (!dirty.value) return true;
  try {
    await confirm({ content: UNSAVED_PLAN_LEAVE_MESSAGE, icon: 'warning' });
    return true;
  } catch {
    return false;
  }
});

onMounted(async () => {
  window.addEventListener('beforeunload', onBeforeUnload);
  await loadMeta();
  await loadVersion();
});

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', onBeforeUnload);
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
            {{ isNew ? planName || '新方案' : version?.plan?.name || '方案' }}
            /
            {{ isNew ? '未保存草稿' : `v${version?.version_no ?? ''}` }}
          </span>
          <VersionStatusTag :value="isNew ? 'draft' : version?.status" />
          <a-select
            :disabled="readonly"
            :options="enumTagOptions(PLAN_MODE_TAG_OPTIONS)"
            :value="modeTag"
            class="w-[160px]"
            @update:value="setModeTag"
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
                  <div class="mb-1 text-sm">备注</div>
                  <a-input
                    :disabled="readonly"
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
                :templates="templates"
                :value="selected.formula_json"
                @update:value="(v) => patchSelected({ formula_json: v })"
              />
            </div>
          </div>
        </div>

        <div
          v-if="accruedHint"
          class="flex flex-wrap items-center gap-2"
        >
          <a-alert class="min-w-0 flex-1" show-icon type="warning" :message="accruedHint" />
          <a-button size="small" type="primary" @click="moveAccruedLast">移到最后</a-button>
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
          <a-tooltip :title="trialHint || undefined">
            <VbenButton v-access:code="'rs:plan:trial'" @click="openTrial">试算</VbenButton>
          </a-tooltip>
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
            :disabled="isNew || version?.status === 'draft'"
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
