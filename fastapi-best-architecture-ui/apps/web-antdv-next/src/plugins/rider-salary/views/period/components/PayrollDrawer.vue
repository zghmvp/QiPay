<script lang="ts" setup>
import type { PayrollDetailItem } from '../../../types/payroll';
import type { PayrollGroupedDetail } from '../../../types/payroll';

import { computed, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { getPayrollApi } from '../../../api/payroll';
import MoneyText from '../../../components/MoneyText.vue';
import StatusTag from '../../../components/StatusTag.vue';
import {
  CALC_STAGE_OPTIONS,
  DAY_STATUS_OPTIONS,
  DETAIL_SOURCE_OPTIONS,
  enumLabel,
  PAYROLL_KIND_OPTIONS,
  PAYROLL_STATUS_OPTIONS,
} from '../../../constants/enums';
import { toDateTimeString } from '../../../utils/date';

const loading = ref(false);
const detail = ref<PayrollGroupedDetail>();
const riderLabel = ref('');

const stages = computed(() => {
  const grouped = detail.value?.details ?? {};
  return CALC_STAGE_OPTIONS.filter((item) => grouped[item.value]?.length).map(
    (item) => ({
      key: item.value,
      label: item.label,
      rows: grouped[item.value] ?? [],
    }),
  );
});

const extraStages = computed(() => {
  const grouped = detail.value?.details ?? {};
  const known = new Set(CALC_STAGE_OPTIONS.map((item) => item.value));
  return Object.keys(grouped)
    .filter((key) => !known.has(key) && grouped[key]?.length)
    .map((key) => ({
      key,
      label: key,
      rows: grouped[key] ?? [],
    }));
});

const allStages = computed(() => [...stages.value, ...extraStages.value]);

const detailColumns = [
  { dataIndex: 'biz_date', title: '日期', width: 110 },
  { dataIndex: 'name', title: '项名称' },
  { dataIndex: 'order_no', title: '订单号', width: 140 },
  { dataIndex: 'source', key: 'source', title: '来源', width: 100 },
  { dataIndex: 'amount', key: 'amount', title: '金额', width: 110 },
];

const dailyColumns = [
  { dataIndex: 'biz_date', title: '日期', width: 120 },
  { dataIndex: 'order_count', title: '单量', width: 80 },
  { dataIndex: 'valid_order_count', title: '有效单', width: 80 },
  { dataIndex: 'formula_amount', key: 'formula_amount', title: '公式金额' },
  { dataIndex: 'manual_bonus', key: 'manual_bonus', title: '手工奖' },
  { dataIndex: 'manual_penalty', key: 'manual_penalty', title: '手工惩' },
  { dataIndex: 'net_adjust', key: 'net_adjust', title: '奖惩净额' },
  { dataIndex: 'day_status', key: 'day_status', title: '日状态', width: 100 },
];

function formatTrace(trace?: null | Record<string, unknown>) {
  if (!trace) return '无计算过程';
  const parts: string[] = [];
  if (trace['条件'] !== undefined) parts.push(`条件：${String(trace['条件'])}`);
  if (trace['条件结果'] !== undefined)
    parts.push(`条件结果：${String(trace['条件结果'])}`);
  if (trace['公式'] !== undefined) parts.push(`公式：${String(trace['公式'])}`);
  if (trace['变量'] !== undefined)
    parts.push(`变量：${JSON.stringify(trace['变量'])}`);
  if (trace['结果'] !== undefined) parts.push(`结果：${String(trace['结果'])}`);
  if (!parts.length) return JSON.stringify(trace);
  return parts.join('\n');
}

const [Drawer, drawerApi] = useVbenDrawer({
  class: 'w-[920px]',
  cancelText: '关闭',
  destroyOnClose: true,
  showConfirmButton: false,
  async onOpenChange(isOpen) {
    if (!isOpen) return;
    const data = drawerApi.getData<{
      id?: number;
      rider_name?: null | string;
    }>();
    riderLabel.value = data?.rider_name || '';
    detail.value = undefined;
    if (!data?.id) return;
    loading.value = true;
    try {
      detail.value = await getPayrollApi(data.id);
    } finally {
      loading.value = false;
    }
  },
});
</script>

<template>
  <Drawer :title="riderLabel ? `薪资明细 · ${riderLabel}` : '薪资明细'">
    <a-spin :spinning="loading">
      <template v-if="detail">
        <a-descriptions bordered size="small" :column="3" class="mb-4">
          <a-descriptions-item label="类型">
            <StatusTag :options="PAYROLL_KIND_OPTIONS" :value="detail.kind" />
          </a-descriptions-item>
          <a-descriptions-item label="状态">
            <StatusTag :options="PAYROLL_STATUS_OPTIONS" :value="detail.status" />
          </a-descriptions-item>
          <a-descriptions-item label="需重算">
            <span :class="detail.stale ? 'font-medium text-red-500' : ''">
              {{ detail.stale ? '是' : '否' }}
            </span>
          </a-descriptions-item>
          <a-descriptions-item label="单量">{{ detail.order_count }}</a-descriptions-item>
          <a-descriptions-item label="有效单">{{ detail.valid_order_count }}</a-descriptions-item>
          <a-descriptions-item label="计算时间">
            {{ toDateTimeString(detail.calc_time) || '—' }}
          </a-descriptions-item>
          <a-descriptions-item label="应发">
            <MoneyText :value="detail.gross" />
          </a-descriptions-item>
          <a-descriptions-item label="代扣">
            <MoneyText :value="detail.deduction_total" />
          </a-descriptions-item>
          <a-descriptions-item label="预支抵扣">
            <MoneyText :value="detail.advance_deduction" />
          </a-descriptions-item>
          <a-descriptions-item label="实发">
            <MoneyText :value="detail.net" />
          </a-descriptions-item>
          <a-descriptions-item label="逐单">
            <MoneyText :value="detail.per_order_total" />
          </a-descriptions-item>
          <a-descriptions-item label="按日">
            <MoneyText :value="detail.daily_total" />
          </a-descriptions-item>
        </a-descriptions>
        <a-alert
          v-if="detail.warnings?.length"
          class="mb-3"
          show-icon
          type="warning"
          :message="detail.warnings.join('；')"
        />
        <h4 class="mb-2 font-medium">明细（按阶段）</h4>
        <a-collapse v-if="allStages.length" class="mb-4">
          <a-collapse-panel
            v-for="stage in allStages"
            :key="stage.key"
            :header="`${stage.label}（${stage.rows.length}）`"
          >
            <a-table
              size="small"
              :columns="detailColumns"
              :data-source="stage.rows"
              :pagination="false"
              :row-key="(row: PayrollDetailItem, index?: number) => row.id ?? `${stage.key}-${index ?? 0}`"
              :expandable="{
                rowExpandable: (row: PayrollDetailItem) => Boolean(row.calc_trace),
              }"
            >
              <template #expandedRowRender="{ record }">
                <pre class="m-0 whitespace-pre-wrap text-xs">{{ formatTrace(record.calc_trace) }}</pre>
              </template>
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'source'">
                  {{ enumLabel(DETAIL_SOURCE_OPTIONS, record.source) }}
                </template>
                <template v-else-if="column.key === 'amount'">
                  <MoneyText signed :value="record.amount" />
                </template>
              </template>
            </a-table>
          </a-collapse-panel>
        </a-collapse>
        <a-empty v-else class="mb-4" description="暂无明细" />
        <h4 class="mb-2 font-medium">日汇总</h4>
        <a-table
          size="small"
          :columns="dailyColumns"
          :data-source="detail.dailies"
          :pagination="false"
          :row-key="(row) => `${row.rider_id}-${row.biz_date}`"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'formula_amount'">
              <MoneyText :value="record.formula_amount" />
            </template>
            <template v-else-if="column.key === 'manual_bonus'">
              <MoneyText signed :value="record.manual_bonus" />
            </template>
            <template v-else-if="column.key === 'manual_penalty'">
              <MoneyText signed :value="record.manual_penalty" />
            </template>
            <template v-else-if="column.key === 'net_adjust'">
              <MoneyText signed :value="record.net_adjust" />
            </template>
            <template v-else-if="column.key === 'day_status'">
              <StatusTag :options="DAY_STATUS_OPTIONS" :value="record.day_status" />
            </template>
          </template>
        </a-table>
      </template>
      <a-empty v-else-if="!loading" description="未找到薪资单" />
    </a-spin>
  </Drawer>
</template>
