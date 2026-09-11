<script lang="ts" setup>
import type { PlanDetail, PlanForm, PlanVersionDetail } from '../../types/plan';

import { computed, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';

import { confirm, useVbenDrawer, useVbenModal, VbenButton } from '@vben/common-ui';
import { MaterialSymbolsAdd } from '@vben/icons';

import { message } from 'antdv-next';

import {
  activatePlanVersionApi,
  copyPlanVersionApi,
  createPlanApi,
  createPlanVersionApi,
  deletePlanApi,
  deletePlanVersionApi,
  disablePlanVersionApi,
  getPlanListApi,
  getPlanVersionListApi,
  putPlanVersionItemsApi,
  updatePlanApi,
  updatePlanVersionApi,
} from '../../api/plan';
import { getAllSubjectsApi } from '../../api/subject';
import { buildItemsFromPreset } from '../../constants/plan-presets';
import type { PlanPreset } from '../../constants/plan-presets';
import { useReasonModal } from '../../components/use-reason-modal';
import {
  ENABLE_STATUS_OPTIONS,
  enumLabel,
  enumTagOptions,
  PLAN_MODE_TAG_OPTIONS,
} from '../../constants/enums';
import { toDateTimeString } from '../../utils/date';
import PageContainer from '../_shared/PageContainer.vue';
import RollbackModal from './components/RollbackModal.vue';
import PlanPresetPicker from './components/PlanPresetPicker.vue';
import TrialPanel from './components/TrialPanel.vue';
import VersionStatusTag from './components/VersionStatusTag.vue';
import {
  activateHint,
  canEditVersion,
  COLOR_PRESETS,
  PLAN_PRESET_COLORS,
  toSaveItems,
  trialLabel,
} from './helpers';

const router = useRouter();
const { ReasonModal, prompt } = useReasonModal();

const loading = ref(false);
const keyword = ref('');
const plans = ref<PlanDetail[]>([]);
const versions = ref<PlanVersionDetail[]>([]);
const allVersions = ref<PlanVersionDetail[]>([]);
const selectedPlanId = ref<number>();
const formMode = ref<'create' | 'edit'>('create');
const form = reactive<PlanForm>({
  code: '',
  color: PLAN_PRESET_COLORS[0] ?? '#1677ff',
  description: '',
  name: '',
  short_name: '',
  status: 'enable',
});
const editingId = ref<number>();

const selectedPlan = computed(() =>
  plans.value.find((item) => item.id === selectedPlanId.value),
);

const planCards = computed(() =>
  plans.value.map((plan) => {
    const list = allVersions.value.filter((item) => item.plan_id === plan.id);
    return {
      ...plan,
      activeCount: list.filter((item) => item.status === 'active').length,
      versionCount: list.length,
    };
  }),
);

const [Drawer, drawerApi] = useVbenDrawer({
  class: 'w-[480px]',
  destroyOnClose: true,
  async onConfirm() {
    if (!form.code.trim() || !form.name.trim() || !form.short_name.trim()) {
      message.warning('请填写编码、名称和短名');
      return;
    }
    drawerApi.lock();
    try {
      if (formMode.value === 'edit' && editingId.value) {
        await updatePlanApi(editingId.value, { ...form });
        message.success('方案已更新');
      } else {
        const created = await createPlanApi({ ...form });
        selectedPlanId.value = created.id;
        message.success('方案已创建');
      }
      await drawerApi.close();
      await loadAll();
    } finally {
      drawerApi.unlock();
    }
  },
});

const [TrialDrawer, trialApi] = useVbenDrawer({ connectedComponent: TrialPanel });
const [RollbackComp, rollbackApi] = useVbenModal({ connectedComponent: RollbackModal });
const [PresetPicker, presetApi] = useVbenModal({ connectedComponent: PlanPresetPicker });

function openCreate() {
  formMode.value = 'create';
  editingId.value = undefined;
  Object.assign(form, {
    code: '',
    color: PLAN_PRESET_COLORS[0] ?? '#1677ff',
    description: '',
    name: '',
    short_name: '',
    status: 'enable',
  });
  drawerApi.open();
}

function openEdit(plan: PlanDetail) {
  formMode.value = 'edit';
  editingId.value = plan.id;
  Object.assign(form, {
    code: plan.code,
    color: plan.color,
    description: plan.description ?? '',
    name: plan.name,
    short_name: plan.short_name,
    status: plan.status,
  });
  drawerApi.open();
}

async function loadAll() {
  loading.value = true;
  try {
    const [planPage, versionPage] = await Promise.all([
      getPlanListApi({
        name: keyword.value || undefined,
        page: 1,
        size: 100,
      }),
      getPlanVersionListApi({ page: 1, size: 200 }),
    ]);
    plans.value = planPage?.items ?? [];
    allVersions.value = versionPage?.items ?? [];
    if (!selectedPlanId.value && plans.value[0]) {
      selectedPlanId.value = plans.value[0].id;
    }
    await loadVersions();
  } finally {
    loading.value = false;
  }
}

async function loadVersions() {
  if (!selectedPlanId.value) {
    versions.value = [];
    return;
  }
  const page = await getPlanVersionListApi({
    page: 1,
    plan_id: selectedPlanId.value,
    size: 100,
  });
  versions.value = page?.items ?? [];
}

async function selectPlan(id: number) {
  selectedPlanId.value = id;
  await loadVersions();
}

function goEditor(row: PlanVersionDetail) {
  router.push(`/rider-salary/plan/editor/${row.id}`);
}

async function createVersion() {
  if (!selectedPlanId.value) {
    message.warning('请先选择方案');
    return;
  }
  const created = await createPlanVersionApi({
    mode_tag: 'custom',
    plan_id: selectedPlanId.value,
  });
  message.success(`已创建空白草稿 v${created.version_no}`);
  router.push(`/rider-salary/plan/editor/${created.id}`);
}

function openCreateFromPreset() {
  if (!selectedPlanId.value) {
    message.warning('请先选择方案');
    return;
  }
  presetApi
    .setData({
      defaultMode: 'replace',
      onApply: (preset: PlanPreset) => {
        void createVersionFromPreset(preset);
      },
    })
    .open();
}

async function createVersionFromPreset(preset: PlanPreset) {
  if (!selectedPlanId.value) return;
  try {
    const subjects = await getAllSubjectsApi();
    const items = buildItemsFromPreset(preset, subjects ?? []);
    const created = await createPlanVersionApi({
      mode_tag: preset.mode_tag,
      plan_id: selectedPlanId.value,
    });
    await putPlanVersionItemsApi(created.id, toSaveItems(items));
    if (preset.mode_tag !== created.mode_tag) {
      await updatePlanVersionApi(created.id, { mode_tag: preset.mode_tag });
    }
    message.success(`已从案例「${preset.name}」创建 v${created.version_no}`);
    router.push(`/rider-salary/plan/editor/${created.id}`);
  } catch (error) {
    message.error(error instanceof Error ? error.message : '从案例创建失败');
  }
}

async function copyVersion(row: PlanVersionDetail) {
  const created = await copyPlanVersionApi(row.id, row.plan_id);
  message.success(`已复制为版本 v${created.version_no} 草稿`);
  router.push(`/rider-salary/plan/editor/${created.id}`);
}

async function removeVersion(row: PlanVersionDetail) {
  try {
    await confirm({ content: `确认删除草稿 v${row.version_no}？`, icon: 'warning' });
  } catch {
    return;
  }
  await deletePlanVersionApi(row.id);
  message.success('已删除');
  await loadAll();
}

async function removePlan(plan: PlanDetail) {
  try {
    await confirm({ content: `确认删除方案「${plan.name}」？`, icon: 'warning' });
  } catch {
    return;
  }
  await deletePlanApi(plan.id);
  message.success('已删除方案');
  if (selectedPlanId.value === plan.id) selectedPlanId.value = undefined;
  await loadAll();
}

async function activate(row: PlanVersionDetail) {
  const hint = activateHint({
    itemsHash: row.items_hash,
    trialHash: row.trial_hash,
    trialPassed: row.trial_passed,
  });
  if (hint) {
    message.warning(hint);
    return;
  }
  await activatePlanVersionApi(row.id);
  message.success('已启用');
  await loadAll();
}

async function disable(row: PlanVersionDetail) {
  const { reason } = await prompt({ title: '停用方案版本' });
  await disablePlanVersionApi(row.id, reason);
  message.success('已停用');
  await loadAll();
}

function trialText(row: PlanVersionDetail) {
  return trialLabel({
    itemsHash: row.items_hash,
    trialHash: row.trial_hash,
    trialPassed: row.trial_passed,
  }).text;
}

const versionColumns = [
  { dataIndex: 'version_no', key: 'version_no', title: '版本号', width: 80 },
  { key: 'status', title: '状态', width: 90 },
  { key: 'mode', title: '模式', width: 110 },
  { key: 'used', title: '已使用', width: 80 },
  { key: 'trial', title: '试算', width: 110 },
  { key: 'created', title: '创建时间', width: 160 },
  { key: 'activated', title: '启用时间', width: 160 },
  { key: 'actions', title: '操作', width: 360 },
];

onMounted(loadAll);
</script>

<template>
  <PageContainer>
    <a-spin class="min-h-0 flex-1" :spinning="loading" wrapper-class-name="h-full">
      <div class="flex h-full min-h-0 gap-3">
        <div class="flex w-[320px] shrink-0 flex-col gap-3">
          <div class="flex gap-2">
            <a-input
              v-model:value="keyword"
              allow-clear
              placeholder="搜索方案名称"
              @press-enter="loadAll"
            />
            <VbenButton v-access:code="'rs:plan:add'" @click="openCreate">
              <MaterialSymbolsAdd class="size-5" />
              新增
            </VbenButton>
          </div>
          <a-empty v-if="planCards.length === 0" description="暂无方案">
            <VbenButton v-access:code="'rs:plan:add'" @click="openCreate">
              去新增方案
            </VbenButton>
          </a-empty>
          <div v-else class="flex flex-col gap-2 overflow-auto">
            <button
              v-for="plan in planCards"
              :key="plan.id"
              class="rounded border p-3 text-left"
              :class="selectedPlanId === plan.id ? 'border-primary bg-primary/5' : 'hover:bg-muted/40'"
              type="button"
              @click="selectPlan(plan.id)"
            >
              <div class="flex items-center gap-2">
                <span
                  class="inline-block size-3 rounded"
                  :style="{ background: plan.color }"
                ></span>
                <span class="font-medium">{{ plan.name }}</span>
                <span class="text-muted-foreground text-xs">{{ plan.code }}</span>
              </div>
              <div class="text-muted-foreground mt-1 text-xs">
                短名 {{ plan.short_name }} · 版本 {{ plan.versionCount }} · 启用
                {{ plan.activeCount }}
              </div>
              <div class="mt-1 truncate text-sm">{{ plan.description || '暂无说明' }}</div>
              <div class="mt-2 flex gap-2" @click.stop>
                <a-button
                  v-access:code="'rs:plan:edit'"
                  size="small"
                  @click="openEdit(plan)"
                >
                  编辑
                </a-button>
                <a-button
                  v-access:code="'rs:plan:del'"
                  danger
                  size="small"
                  @click="removePlan(plan)"
                >
                  删除
                </a-button>
              </div>
            </button>
          </div>
        </div>

        <div class="min-w-0 flex-1">
          <div class="mb-3 flex items-center justify-between">
            <div class="font-medium">
              {{ selectedPlan ? `${selectedPlan.name} 的版本` : '请选择方案' }}
            </div>
            <a-dropdown-button v-access:code="'rs:plan:add'" :disabled="!selectedPlanId">
              <span @click="createVersion">新建空白版本</span>
              <template #overlay>
                <a-menu>
                  <a-menu-item key="preset" @click="openCreateFromPreset">
                    从方案案例创建…
                  </a-menu-item>
                </a-menu>
              </template>
            </a-dropdown-button>
          </div>
          <a-empty
            v-if="!selectedPlanId"
            description="请先选择左侧方案"
          />
          <a-table
            v-else
            :columns="versionColumns"
            :data-source="versions"
            :pagination="false"
            :scroll="{ x: 1200 }"
            row-key="id"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <VersionStatusTag v-if="column.key === 'status'" :value="record.status" />
              <template v-else-if="column.key === 'mode'">
                {{ enumLabel(PLAN_MODE_TAG_OPTIONS, record.mode_tag) }}
              </template>
              <template v-else-if="column.key === 'used'">
                {{ record.is_used ? '是' : '否' }}
              </template>
              <template v-else-if="column.key === 'trial'">
                {{ trialText(record) }}
              </template>
              <template v-else-if="column.key === 'created'">
                {{ toDateTimeString(record.created_time) }}
              </template>
              <template v-else-if="column.key === 'activated'">
                {{ toDateTimeString(record.activated_time) || '—' }}
              </template>
              <a-space v-else-if="column.key === 'actions'" wrap>
                <a-button size="small" @click="goEditor(record)">
                  {{ canEditVersion(record.status, record.is_used) ? '编辑' : '查看' }}
                </a-button>
                <a-button
                  v-access:code="'rs:plan:trial'"
                  size="small"
                  @click="
                    trialApi
                      .setData({ onSuccess: loadAll, versionId: record.id })
                      .open()
                  "
                >
                  试算
                </a-button>
                <a-tooltip
                  v-if="record.status === 'draft'"
                  :title="
                    activateHint({
                      itemsHash: record.items_hash,
                      trialHash: record.trial_hash,
                      trialPassed: record.trial_passed,
                    }) || '启用'
                  "
                >
                  <span>
                    <a-button
                      v-access:code="'rs:plan:activate'"
                      :disabled="
                        Boolean(
                          activateHint({
                            itemsHash: record.items_hash,
                            trialHash: record.trial_hash,
                            trialPassed: record.trial_passed,
                          }),
                        )
                      "
                      size="small"
                      type="primary"
                      @click="activate(record)"
                    >
                      启用
                    </a-button>
                  </span>
                </a-tooltip>
                <a-button
                  v-if="record.status === 'active'"
                  v-access:code="'rs:plan:disable'"
                  size="small"
                  @click="disable(record)"
                >
                  停用
                </a-button>
                <a-button
                  v-access:code="'rs:plan:copy'"
                  size="small"
                  @click="copyVersion(record)"
                >
                  复制
                </a-button>
                <a-button
                  v-if="canEditVersion(record.status, record.is_used)"
                  v-access:code="'rs:plan:del'"
                  danger
                  size="small"
                  @click="removeVersion(record)"
                >
                  删除
                </a-button>
                <a-button
                  v-if="record.status === 'active' || record.status === 'disabled'"
                  v-access:code="'rs:plan:rollback'"
                  danger
                  size="small"
                  @click="
                    rollbackApi
                      .setData({
                        onSuccess: (id?: number) =>
                          id
                            ? router.push(`/rider-salary/plan/editor/${id}`)
                            : loadAll(),
                        planId: record.plan_id,
                        versionId: record.id,
                      })
                      .open()
                  "
                >
                  回退
                </a-button>
              </a-space>
            </template>
          </a-table>
        </div>
      </div>
    </a-spin>

    <Drawer :title="formMode === 'edit' ? '编辑方案' : '新增方案'">
      <a-form layout="vertical">
        <a-form-item label="编码" required>
          <a-input v-model:value="form.code" :disabled="formMode === 'edit'" />
        </a-form-item>
        <a-form-item label="名称" required>
          <a-input v-model:value="form.name" />
        </a-form-item>
        <a-form-item label="短名" required>
          <a-input v-model:value="form.short_name" :maxlength="16" />
        </a-form-item>
        <a-form-item label="颜色">
          <div class="flex flex-col gap-2">
            <a-color-picker
              v-model:value="form.color"
              :presets="COLOR_PRESETS"
              disabled-alpha
              show-text
              value-format="hex"
            />
            <div class="flex flex-wrap gap-1">
              <button
                v-for="color in PLAN_PRESET_COLORS"
                :key="color"
                class="size-5 rounded border"
                :style="{ background: color }"
                type="button"
                @click="form.color = color"
              ></button>
            </div>
          </div>
        </a-form-item>
        <a-form-item label="说明">
          <a-textarea v-model:value="form.description" :rows="3" />
        </a-form-item>
        <a-form-item label="状态">
          <a-select
            v-model:value="form.status"
            :options="enumTagOptions(ENABLE_STATUS_OPTIONS)"
          />
        </a-form-item>
      </a-form>
    </Drawer>
    <TrialDrawer />
    <RollbackComp />
    <PresetPicker />
    <ReasonModal />
  </PageContainer>
</template>
