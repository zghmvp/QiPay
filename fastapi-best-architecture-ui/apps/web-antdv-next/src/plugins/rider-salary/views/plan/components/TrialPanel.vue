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
/** full_version = 整版试算；binding_segments = 按绑定分段 */
const trialMode = ref<'binding_segments' | 'full_version'>('full_version');

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
    trialMode.value = 'full_version';
  },
});

const versionId = computed(
  () => drawerApi.getData<{ versionId?: number }>()?.versionId,
);

const orderCompare = computed(() => {
  const summary = result.value?.summary;
  if (!summary) return null;
  const valid = Number(summary.valid_order_count ?? summary.order_count ?? 0);
  const plan = Number(
    summary.plan_order_count ?? summary.valid_order_count ?? summary.order_count ?? 0,
  );
  const segments = summary.segment_order_counts ?? [];
  return {
    differs: valid !== plan || segments.length > 1,
    plan,
    segments,
    valid,
  };
});

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
      mode: trialMode.value,
      rider_id: riderId.value,
      start_date: range.value[0],
    });
    result.value = data;
    if (data.passed) {
      message.success(
        trialMode.value === 'binding_segments'
          ? '分段试算完成'
          : '试算通过',
      );
      if (trialMode.value === 'full_version') {
        drawerApi.getData<{ onSuccess?: () => void }>()?.onSuccess?.();
        emit('success');
      }
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
        :message="
          trialMode === 'binding_segments'
            ? '按绑定分段试算：应发与同骑手同周期正式 calculate 同源（预支仍不扣）。使用骑手真实方案绑定切段，含已录入奖惩。换绑场景下「周期有效单量」与「方案期内单量」可不相等。本模式不写入启用门槛。'
            : '整版试算：假定该版本在区间内全程生效，含已录入奖惩，不含预支抵扣。通过后可启用该版本。'
        "
      />
      <a-radio-group
        v-model:value="trialMode"
        button-style="solid"
        data-testid="trial-mode"
      >
        <a-radio-button value="full_version">整版试算</a-radio-button>
        <a-radio-button value="binding_segments">按绑定分段试算</a-radio-button>
      </a-radio-group>
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
        <div v-else class="flex flex-col gap-3" data-testid="trial-result">
          <a-alert
            v-if="result.matches_official_calculate"
            type="success"
            show-icon
            data-testid="trial-matches-official-calculate"
            message="应发与同骑手同周期正式 calculate 同源（预支仍不扣）"
          />
          <a-card v-if="orderCompare" size="small" class="border-primary/30">
            <div class="mb-2 text-sm font-medium">单量口径对照</div>
            <div class="grid grid-cols-2 gap-3 md:grid-cols-2">
              <div class="rounded bg-muted/40 px-3 py-2">
                <div class="text-muted-foreground text-xs">周期有效单量</div>
                <div
                  class="text-xl font-semibold tabular-nums"
                  data-testid="trial-valid-order-count"
                >
                  {{ orderCompare.valid }}
                </div>
                <div class="text-muted-foreground mt-1 text-xs">
                  整个试算区间 completed 单量
                </div>
              </div>
              <div class="rounded bg-muted/40 px-3 py-2">
                <div class="text-muted-foreground text-xs">方案期内单量</div>
                <div
                  class="text-xl font-semibold tabular-nums"
                  data-testid="trial-plan-order-count"
                >
                  {{ orderCompare.plan }}
                </div>
                <div class="text-muted-foreground mt-1 text-xs">
                  各绑定生效段内 completed 单量合计（无方案日不计）
                </div>
              </div>
            </div>
            <a-alert
              class="mt-3"
              :type="orderCompare.differs ? 'warning' : 'info'"
              show-icon
              :message="
                orderCompare.differs
                  ? '两值不同：阶梯/提成请确认公式字段选「周期有效单量」还是「方案期内单量」。'
                  : trialMode === 'full_version'
                    ? '整版试算假定本版本全程生效，两值通常相等；请切换「按绑定分段试算」验证换绑分叉。'
                    : '当前绑定在区间内未产生口径分叉（可能无换绑或无方案日无单）。'
              "
            />
            <div
              v-if="orderCompare.segments.length > 1"
              class="text-muted-foreground mt-2 space-y-1 text-xs"
              data-testid="trial-segment-counts"
            >
              <div
                v-for="seg in orderCompare.segments"
                :key="`${seg.plan_version_id}-${seg.start_date}`"
              >
                段 {{ seg.start_date }}~{{ seg.end_date }}（版本
                {{ seg.plan_version_id }}）：方案期内单量
                {{ seg.plan_order_count }}
              </div>
            </div>
          </a-card>
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
