<script lang="ts" setup>
import type { TrialResult } from '../../../types/plan';

import { computed, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { message } from 'antdv-next';

import { trialPlanVersionApi } from '../../../api/plan';
import MoneyText from '../../../components/MoneyText.vue';
import RiderSelect from '../../../components/RiderSelect.vue';
import SiteSelect from '../../../components/SiteSelect.vue';
import { lastNaturalMonth } from '../helpers';

const emit = defineEmits<{
  success: [];
}>();

const loading = ref(false);
const siteId = ref<number>();
const riderId = ref<number>();
const range = ref<[string, string]>(lastNaturalMonth());
const result = ref<TrialResult>();

const [Drawer, drawerApi] = useVbenDrawer({
  class: 'w-[960px]',
  cancelText: '关闭',
  confirmText: '开始试算',
  destroyOnClose: true,
  async onConfirm() {
    await runTrial();
  },
  onOpenChange(isOpen) {
    if (!isOpen) return;
    siteId.value = undefined;
    riderId.value = undefined;
    range.value = lastNaturalMonth();
    result.value = undefined;
  },
});

const versionId = computed(
  () => drawerApi.getData<{ versionId?: number }>()?.versionId,
);

const cards = computed(() => {
  const summary = result.value?.summary;
  if (!summary) return [];
  return [
    { label: '单量', value: summary.order_count },
    { label: '逐单', money: summary.per_order_total },
    { label: '按日', money: summary.daily_total },
    { label: '周期项', money: summary.period_total },
    { label: '手工奖', money: summary.manual_bonus ?? summary.bonus_total },
    { label: '手工惩', money: summary.manual_penalty ?? summary.penalty_total },
    { label: '应发', money: summary.gross },
    { label: '代扣', money: summary.deduction_total },
    { label: '实发', money: summary.net },
  ];
});

const warnings = computed(() => [
  ...(result.value?.warnings ?? []),
  ...(result.value?.summary?.warnings ?? []),
]);

async function runTrial() {
  const pk = versionId.value;
  if (!pk) return;
  if (!riderId.value) {
    message.warning('请选择骑手');
    return;
  }
  if (!range.value?.[0] || !range.value[1]) {
    message.warning('请选择日期范围');
    return;
  }
  loading.value = true;
  drawerApi.lock();
  try {
    const data = await trialPlanVersionApi(pk, {
      end_date: range.value[1],
      rider_id: riderId.value,
      start_date: range.value[0],
    });
    result.value = data;
    if (data.passed) {
      message.success('试算通过');
      drawerApi.getData<{ onSuccess?: () => void }>()?.onSuccess?.();
      emit('success');
    } else {
      message.warning('试算未通过，请查看警告');
    }
  } finally {
    loading.value = false;
    drawerApi.unlock();
  }
}

function traceText(trace?: Record<string, unknown>) {
  if (!trace) return '无计算过程';
  return Object.entries(trace)
    .map(([key, value]) => `${key}：${typeof value === 'object' ? JSON.stringify(value) : String(value)}`)
    .join('\n');
}

const perOrderColumns = [
  { dataIndex: 'order_no', key: 'order_no', title: '订单号' },
  { dataIndex: 'biz_date', key: 'biz_date', title: '日期', width: 120 },
];

const dailyColumns = [
  { dataIndex: 'biz_date', key: 'biz_date', title: '日期' },
  { dataIndex: 'order_count', key: 'order_count', title: '单量' },
  { key: 'amount', title: '金额' },
  { dataIndex: 'day_status', key: 'day_status', title: '日状态' },
];

const periodColumns = [
  { dataIndex: 'name', key: 'name', title: '项名称' },
  { key: 'amount', title: '金额' },
];
</script>

<template>
  <Drawer title="方案试算">
    <div class="flex flex-col gap-3">
      <a-alert
        type="info"
        show-icon
        message="试算含已录入奖惩，不含预支抵扣。假定该版本在区间内全程生效。"
      />
      <div class="flex flex-wrap gap-2">
        <SiteSelect v-model:value="siteId" />
        <RiderSelect v-model:value="riderId" :site-id="siteId" />
        <a-range-picker v-model:value="range" value-format="YYYY-MM-DD" />
      </div>
      <a-spin :spinning="loading">
        <a-empty
          v-if="!result"
          description="选择站点、骑手与日期后点击「开始试算」"
        />
        <div v-else class="flex flex-col gap-3">
          <div class="grid grid-cols-2 gap-2 md:grid-cols-5">
            <a-card v-for="card in cards" :key="card.label" size="small">
              <div class="text-muted-foreground text-xs">{{ card.label }}</div>
              <div class="text-lg font-medium">
                <MoneyText v-if="card.money !== undefined" :value="card.money" />
                <span v-else>{{ card.value }}</span>
              </div>
            </a-card>
          </div>
          <a-tabs>
            <a-tab-pane key="per_order" tab="逐单明细">
              <a-table
                :columns="perOrderColumns"
                :data-source="result.per_order"
                :expandable="{}"
                :pagination="{ pageSize: 8 }"
                row-key="order_no"
                size="small"
              >
                <template #expandedRowRender="{ record }">
                  <div
                    v-for="(item, idx) in record.items"
                    :key="idx"
                    class="mb-2 rounded border p-2 text-sm"
                  >
                    <div class="mb-1 font-medium">
                      {{ item.name }}
                      <MoneyText :value="item.amount" />
                    </div>
                    <pre class="text-muted-foreground whitespace-pre-wrap text-xs">{{
                      traceText(item.calc_trace)
                    }}</pre>
                  </div>
                </template>
              </a-table>
            </a-tab-pane>
            <a-tab-pane key="daily" tab="按日汇总">
              <a-table
                :columns="dailyColumns"
                :data-source="result.daily"
                :pagination="{ pageSize: 10 }"
                row-key="biz_date"
                size="small"
              >
                <template #bodyCell="{ column, record }">
                  <MoneyText v-if="column.key === 'amount'" :value="record.amount" />
                </template>
              </a-table>
            </a-tab-pane>
            <a-tab-pane key="period" tab="周期项">
              <a-table
                :columns="periodColumns"
                :data-source="result.period_items"
                :expandable="{}"
                :pagination="false"
                row-key="name"
                size="small"
              >
                <template #bodyCell="{ column, record }">
                  <MoneyText v-if="column.key === 'amount'" :value="record.amount" />
                </template>
                <template #expandedRowRender="{ record }">
                  <pre class="text-muted-foreground whitespace-pre-wrap text-xs">{{
                    traceText(record.calc_trace)
                  }}</pre>
                </template>
              </a-table>
            </a-tab-pane>
            <a-tab-pane key="warnings" tab="警告">
              <a-empty v-if="warnings.length === 0" description="无警告" />
              <a-alert
                v-for="(item, idx) in warnings"
                :key="idx"
                class="mb-2"
                :message="item"
                type="warning"
                show-icon
              />
            </a-tab-pane>
          </a-tabs>
        </div>
      </a-spin>
    </div>
  </Drawer>
</template>
