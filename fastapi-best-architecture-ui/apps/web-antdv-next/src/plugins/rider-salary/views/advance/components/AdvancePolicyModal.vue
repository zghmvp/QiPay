<script lang="ts" setup>
import type { AdvancePolicy } from '../../../types/advance';
import type { SiteResult } from '../../../types/site';

import { computed, reactive, ref, watch } from 'vue';

import { message } from 'antdv-next';

import { getAdvancePolicyApi, saveAdvancePolicyApi } from '../../../api/advance';
import { getAllSitesApi } from '../../../api/site';

const open = defineModel<boolean>('open', { default: false });

const loading = ref(false);
const saving = ref(false);
const sites = ref<SiteResult[]>([]);
const source = ref<AdvancePolicy['source']>('builtin');

const form = reactive({
  site_id: 0,
  amount_mode: 'percent' as 'fixed' | 'percent',
  percent: 50,
  fixed_amount: 3000,
  max_amount: undefined as number | undefined,
  monthly_max_count: 2,
  min_tenure_days: 7,
  min_completed_orders: 1,
  min_amount: 1,
});

const siteOptions = computed(() => [
  { label: '全局默认', value: 0 },
  ...sites.value.map((item) => ({
    label: `${item.name}（${item.code}）`,
    value: item.id,
  })),
]);

const sourceText = computed(() => {
  if (form.site_id === 0 && source.value === 'global') {
    return '这是已保存的全局规则，没有单独配置的站点都会沿用。';
  }
  if (form.site_id !== 0 && source.value === 'site') {
    return '这是该站点单独保存的规则。';
  }
  if (source.value === 'global') {
    return '该站点还没有单独保存，正在沿用全局规则。保存后只对该站点生效。';
  }
  return '还没有保存过规则，下面是系统默认。保存后开始生效。';
});

async function loadSites() {
  sites.value = await getAllSitesApi();
}

function applyPolicy(data: AdvancePolicy) {
  source.value = data.source;
  form.amount_mode = data.amount_mode;
  form.percent = Number(data.percent);
  form.fixed_amount = Number(data.fixed_amount);
  form.max_amount = data.max_amount == null ? undefined : Number(data.max_amount);
  form.monthly_max_count = data.monthly_max_count;
  form.min_tenure_days = data.min_tenure_days;
  form.min_completed_orders = data.min_completed_orders;
  form.min_amount = Number(data.min_amount);
}

async function loadPolicy(fallback = true) {
  loading.value = true;
  try {
    applyPolicy(await getAdvancePolicyApi(form.site_id));
  } catch (error) {
    if (fallback && form.site_id === 0 && sites.value[0]) {
      form.site_id = sites.value[0].id;
      loading.value = false;
      await loadPolicy(false);
      return;
    }
    throw error;
  } finally {
    loading.value = false;
  }
}

watch(open, async (visible) => {
  if (!visible) return;
  if (!sites.value.length) await loadSites();
  await loadPolicy();
});

async function onSave() {
  saving.value = true;
  try {
    const saved = await saveAdvancePolicyApi({
      site_id: form.site_id,
      amount_mode: form.amount_mode,
      percent: form.percent,
      fixed_amount: form.fixed_amount,
      max_amount: form.max_amount ?? null,
      monthly_max_count: form.monthly_max_count,
      min_tenure_days: form.min_tenure_days,
      min_completed_orders: form.min_completed_orders,
      min_amount: form.min_amount,
    });
    source.value = saved.source;
    message.success('预支规则已保存');
    open.value = false;
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <a-modal
    v-model:open="open"
    title="预支规则"
    :footer="null"
    width="720"
    destroy-on-close
  >
    <a-spin :spinning="loading">
      <a-alert class="policy-note" type="info" show-icon :message="sourceText" />
      <a-form class="policy-form" layout="vertical">
        <a-form-item label="适用范围">
          <a-select v-model:value="form.site_id" :options="siteOptions" @change="loadPolicy" />
        </a-form-item>
        <a-form-item label="额度怎么算">
          <a-radio-group v-model:value="form.amount_mode" class="policy-modes">
            <a-radio value="percent">按当前周期预估实发的百分比</a-radio>
            <a-radio value="fixed">固定额度</a-radio>
          </a-radio-group>
        </a-form-item>
        <div class="policy-grid">
          <a-form-item v-if="form.amount_mode === 'percent'" label="预估实发百分比">
            <a-input-number
              v-model:value="form.percent"
              :min="1"
              :max="100"
              :precision="0"
              addon-after="%"
            />
          </a-form-item>
          <a-form-item v-else label="固定额度">
            <a-input-number
              v-model:value="form.fixed_amount"
              :min="0.01"
              :precision="2"
              addon-after="元"
            />
          </a-form-item>
          <a-form-item label="绝对封顶">
            <a-input-number
              v-model:value="form.max_amount"
              :min="0"
              :precision="2"
              addon-after="元"
              placeholder="不填表示不封顶"
            />
          </a-form-item>
          <a-form-item label="每月最多次数">
            <a-input-number v-model:value="form.monthly_max_count" :min="0" :max="31" addon-after="次" />
          </a-form-item>
          <a-form-item label="入职满多少天">
            <a-input-number v-model:value="form.min_tenure_days" :min="0" addon-after="天" />
          </a-form-item>
          <a-form-item label="本周期至少完成">
            <a-input-number v-model:value="form.min_completed_orders" :min="0" addon-after="单" />
          </a-form-item>
          <a-form-item label="单笔最低金额">
            <a-input-number v-model:value="form.min_amount" :min="0.01" :precision="2" addon-after="元" />
          </a-form-item>
        </div>
      </a-form>
      <p class="policy-hint">
        同时只能有一笔待审核或待发放的预支。驳回和撤回不占本月次数。没有绑定薪资方案时，预估实发是 0，按百分比就不能预支。
      </p>
      <div class="policy-footer">
        <a-button :auto-insert-space="false" @click="open = false">取消</a-button>
        <a-button type="primary" :auto-insert-space="false" :loading="saving" @click="onSave">
          保存
        </a-button>
      </div>
    </a-spin>
  </a-modal>
</template>

<style scoped>
.policy-note {
  margin-bottom: 16px;
}

.policy-form :deep(.ant-form-item) {
  margin-bottom: 12px;
}

.policy-modes {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.policy-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  column-gap: 16px;
}

.policy-grid :deep(.ant-form-item) {
  margin-bottom: 12px;
}

.policy-grid :deep(.ant-input-number),
.policy-grid :deep(.ant-input-number-group-wrapper),
.policy-grid :deep(.ant-space-compact) {
  width: 100%;
}

.policy-hint {
  margin: 4px 0 0;
  color: var(--ant-color-text-secondary, rgb(0 0 0 / 45%));
  font-size: 12px;
  line-height: 20px;
}

.policy-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
</style>
