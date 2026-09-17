<script lang="ts" setup>
import type {
  CalendarDailyItem,
  CalendarDayDetail,
  CalendarHitDetail,
} from '../../../types/calendar';

import { computed, ref, watch } from 'vue';
import { useRouter } from 'vue-router';

import { useAccess } from '@vben/access';
import { VbenButton } from '@vben/common-ui';

import dayjs from 'dayjs';

import { getCalendarDayApi } from '../../../api/calendar';
import MoneyText from '../../../components/MoneyText.vue';
import StatusTag from '../../../components/StatusTag.vue';
import {
  DAY_STATUS_OPTIONS,
  enumLabel,
  ORDER_STATUS_OPTIONS,
  PERIOD_STATUS_OPTIONS,
  PLAN_MODE_TAG_OPTIONS,
  SUBJECT_DIRECTION_OPTIONS,
} from '../../../constants/enums';
import { toDateTimeString } from '../../../utils/date';

const props = defineProps<{
  date?: string;
  open: boolean;
  riderId?: number;
  riderName?: string;
  siteId?: number;
}>();

const emit = defineEmits<{
  shiftDate: [date: string];
  'update:open': [value: boolean];
}>();

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];

const router = useRouter();
const { hasAccessByCodes } = useAccess();
const loading = ref(false);
const detail = ref<CalendarDayDetail>();
const canGoCalculate = computed(() => {
  const status = detail.value?.period?.status;
  return (
    Boolean(detail.value?.period?.id) &&
    (status === 'open' || status === 'reopened') &&
    hasAccessByCodes(['rs:period:calculate'])
  );
});

const title = computed(() => {
  if (!props.date) return '日详情';
  const d = dayjs(props.date);
  const name = props.riderName ? ` · ${props.riderName}` : '';
  return `${d.format('M月D日')} 星期${WEEKDAYS[d.day()]}${name}`;
});

const holidayTag = computed(() => (detail.value?.is_holiday ? '节假日' : ''));

const orderColumns = [
  { dataIndex: 'order_no', key: 'order_no', title: '订单号', width: 140 },
  { dataIndex: 'order_time', key: 'order_time', title: '下单', width: 160 },
  { dataIndex: 'deliver_time', key: 'deliver_time', title: '送达', width: 160 },
  { dataIndex: 'distance_km', key: 'distance_km', title: '距离', width: 80 },
  { dataIndex: 'weight_jin', key: 'weight_jin', title: '重量', width: 80 },
  { dataIndex: 'status', key: 'status', title: '状态', width: 90 },
  { dataIndex: 'amount', key: 'amount', title: '该单金额', width: 100 },
];

const dailyColumns = [
  { dataIndex: 'subject', key: 'subject', title: '科目' },
  { dataIndex: 'name', key: 'name', title: '项名称' },
  { dataIndex: 'amount', key: 'amount', title: '金额', width: 120 },
];

const adjColumns = [
  { dataIndex: 'subject', key: 'subject', title: '科目' },
  { dataIndex: 'direction', key: 'direction', title: '方向', width: 80 },
  { dataIndex: 'amount', key: 'amount', title: '金额', width: 120 },
  { dataIndex: 'remark', key: 'remark', title: '备注' },
];

function traceRows(trace?: null | Record<string, unknown>) {
  if (!trace) return [];
  return [
    { key: '条件', value: String(trace['条件'] ?? '—') },
    {
      key: '条件结果',
      value: trace['条件结果'] === true ? '真' : trace['条件结果'] === false ? '假' : String(trace['条件结果'] ?? '—'),
    },
    { key: '公式', value: String(trace['公式'] ?? '—') },
    {
      key: '变量',
      value:
        trace['变量'] && typeof trace['变量'] === 'object'
          ? Object.entries(trace['变量'] as Record<string, unknown>)
              .map(([k, v]) => `${k}=${v}`)
              .join('，') || '—'
          : '—',
    },
    { key: '结果', value: String(trace['结果'] ?? '—') },
  ];
}

async function load() {
  if (!props.riderId || !props.date) {
    detail.value = undefined;
    return;
  }
  loading.value = true;
  try {
    detail.value = await getCalendarDayApi(props.riderId, props.date);
  } catch {
    detail.value = undefined;
  } finally {
    loading.value = false;
  }
}

watch(
  () => [props.open, props.riderId, props.date] as const,
  ([isOpen]) => {
    if (isOpen) load();
  },
  { immediate: true },
);

function close() {
  emit('update:open', false);
}

function goAdjustment() {
  if (!props.riderId || !props.date) return;
  const siteId = props.siteId;
  router.push({
    path: '/rider-salary/adjustment',
    query: {
      date_from: props.date,
      date_to: props.date,
      rider_id: String(props.riderId),
      ...(siteId ? { site_id: String(siteId) } : {}),
    },
  });
}

function goPeriod() {
  const id = detail.value?.period?.id;
  if (!id) return;
  router.push({ path: '/rider-salary/period', query: { id: String(id) } });
}

function goCalculate() {
  const id = detail.value?.period?.id;
  if (!id) return;
  emit('update:open', false);
  router.push({ path: `/rider-salary/period/${id}/calculate` });
}

function goPlan() {
  const vid = detail.value?.plan?.version_id;
  if (!vid) return;
  router.push(`/rider-salary/plan/editor/${vid}`);
}

function goBinding() {
  if (!props.riderId) return;
  router.push({
    path: `/rider-salary/rider/${props.riderId}`,
    query: { tab: 'binding' },
  });
}

function onKey(e: KeyboardEvent) {
  if (!props.open || !props.date) return;
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    emit(
      'shiftDate',
      dayjs(props.date)
        .add(e.key === 'ArrowRight' ? 1 : -1, 'day')
        .format('YYYY-MM-DD'),
    );
  }
}
</script>

<template>
  <a-drawer
    :open="open"
    :title="title"
    :width="720"
    destroy-on-close
    @close="close"
    @keydown="onKey"
  >
    <a-spin :spinning="loading">
      <div v-if="detail" class="flex flex-col gap-4">
        <a-descriptions :column="2" bordered size="small">
          <a-descriptions-item label="当日方案">
            <template v-if="detail.plan?.plan_name">
              {{ detail.plan.plan_name }}
              <span v-if="detail.plan.short_name">（{{ detail.plan.short_name }}）</span>
              <span v-if="detail.plan.version_no != null"> v{{ detail.plan.version_no }}</span>
              <span v-if="detail.plan.mode_tag" class="ml-1">
                {{ enumLabel(PLAN_MODE_TAG_OPTIONS, detail.plan.mode_tag) }}
              </span>
              <a-button class="ml-2" size="small" type="link" @click="goPlan">
                查看方案
              </a-button>
            </template>
            <span v-else>当日无生效方案</span>
          </a-descriptions-item>
          <a-descriptions-item label="归属周期">
            <template v-if="detail.period?.id">
              {{ detail.period.range }}
              <StatusTag
                class="ml-1"
                :options="PERIOD_STATUS_OPTIONS"
                :value="detail.period.status"
              />
            </template>
            <span v-else>—</span>
          </a-descriptions-item>
          <a-descriptions-item label="日状态">
            <StatusTag :options="DAY_STATUS_OPTIONS" :value="detail.day_status" />
          </a-descriptions-item>
          <a-descriptions-item label="节假日">
            <a-tag v-if="holidayTag">{{ holidayTag }}</a-tag>
            <span v-else>—</span>
          </a-descriptions-item>
        </a-descriptions>

        <a-alert
          v-if="detail.day_status === 'no_plan'"
          show-icon
          type="warning"
          message="当日无生效方案。若有完成单，算薪将硬失败，请先绑定方案。"
        >
          <template #action>
            <a-button
              size="small"
              type="link"
              data-testid="drawer-bind-plan"
              @click="goBinding"
            >
              去绑定方案
            </a-button>
          </template>
        </a-alert>
        <a-alert
          v-else-if="detail.period?.status === 'locked' || detail.period?.status === 'paid'"
          show-icon
          type="info"
          message="该日已锁账，修改请走反冲补发"
        />

        <div class="grid grid-cols-2 gap-2 md:grid-cols-5">
          <a-card size="small">
            <div class="text-muted-foreground text-xs">单量</div>
            <div class="text-lg font-medium">{{ detail.totals.order_count }}</div>
          </a-card>
          <a-card size="small">
            <div class="text-muted-foreground text-xs">公式金额</div>
            <div class="text-lg font-medium">
              <MoneyText :value="detail.totals.formula_amount" />
            </div>
          </a-card>
          <a-card size="small">
            <div class="text-muted-foreground text-xs">手工奖</div>
            <div class="text-lg font-medium">
              <MoneyText signed :value="detail.totals.manual_bonus" />
            </div>
          </a-card>
          <a-card size="small">
            <div class="text-muted-foreground text-xs">手工惩</div>
            <div class="text-lg font-medium">
              <MoneyText signed :value="detail.totals.manual_penalty" />
            </div>
          </a-card>
          <a-card size="small">
            <div class="text-muted-foreground text-xs">净额</div>
            <div class="text-lg font-medium">
              <MoneyText signed :value="detail.totals.net" />
            </div>
          </a-card>
        </div>

        <a-tabs>
          <a-tab-pane key="orders" tab="订单列表">
            <a-empty v-if="!detail.orders.length" description="当日没有订单" />
            <a-table
              v-else
              :columns="orderColumns"
              :data-source="detail.orders"
              :expandable="{}"
              :pagination="false"
              row-key="id"
              size="small"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'order_time'">
                  {{ toDateTimeString(record.order_time) }}
                </template>
                <template v-else-if="column.key === 'deliver_time'">
                  {{ toDateTimeString(record.deliver_time) || '—' }}
                </template>
                <template v-else-if="column.key === 'status'">
                  <StatusTag :options="ORDER_STATUS_OPTIONS" :value="record.status" />
                </template>
                <template v-else-if="column.key === 'amount'">
                  <MoneyText :value="record.amount" />
                </template>
                <template v-else-if="column.key === 'distance_km'">
                  {{ record.distance_km ?? '—' }}
                </template>
                <template v-else-if="column.key === 'weight_jin'">
                  {{ record.weight_jin ?? '—' }}
                </template>
              </template>
              <template #expandedRowRender="{ record }">
                <div
                  v-if="!record.details?.length"
                  class="text-muted-foreground text-xs"
                >
                  无命中项
                </div>
                <div
                  v-for="(hit, idx) in (record.details as CalendarHitDetail[])"
                  :key="idx"
                  class="mb-2 rounded border p-2"
                >
                  <div class="mb-1 font-medium">
                    {{ hit.subject }}
                    <MoneyText class="ml-2" :value="hit.amount" />
                  </div>
                  <a-table
                    :columns="[
                      { dataIndex: 'key', key: 'key', title: '字段', width: 100 },
                      { dataIndex: 'value', key: 'value', title: '值' },
                    ]"
                    :data-source="traceRows(hit.calc_trace)"
                    :pagination="false"
                    row-key="key"
                    size="small"
                  />
                </div>
              </template>
            </a-table>
          </a-tab-pane>
          <a-tab-pane key="daily" tab="按日项">
            <a-empty v-if="!detail.daily_items.length" description="无按日项" />
            <a-table
              v-else
              :columns="dailyColumns"
              :data-source="detail.daily_items"
              :expandable="{}"
              :pagination="false"
              :row-key="(row: CalendarDailyItem) => `${row.subject}-${row.name}`"
              size="small"
            >
              <template #bodyCell="{ column, record }">
                <MoneyText v-if="column.key === 'amount'" :value="record.amount" />
              </template>
              <template #expandedRowRender="{ record }">
                <a-table
                  :columns="[
                    { dataIndex: 'key', key: 'key', title: '字段', width: 100 },
                    { dataIndex: 'value', key: 'value', title: '值' },
                  ]"
                  :data-source="traceRows(record.calc_trace)"
                  :pagination="false"
                  row-key="key"
                  size="small"
                />
              </template>
            </a-table>
          </a-tab-pane>
          <a-tab-pane key="adj" tab="奖惩明细">
            <a-empty v-if="!detail.adjustments.length" description="无奖惩记录" />
            <a-table
              v-else
              :columns="adjColumns"
              :data-source="detail.adjustments"
              :pagination="false"
              row-key="id"
              size="small"
            >
              <template #bodyCell="{ column, record }">
                <StatusTag
                  v-if="column.key === 'direction'"
                  :options="SUBJECT_DIRECTION_OPTIONS"
                  :value="record.direction"
                />
                <MoneyText
                  v-else-if="column.key === 'amount'"
                  signed
                  :value="record.amount"
                />
              </template>
            </a-table>
          </a-tab-pane>
        </a-tabs>
      </div>
    </a-spin>
    <template #footer>
      <div class="flex justify-end gap-2">
        <VbenButton
          variant="outline"
          data-testid="calendar-go-adjustment"
          @click="goAdjustment"
        >
          录入奖惩
        </VbenButton>
        <VbenButton :disabled="!detail?.period?.id" @click="goPeriod">
          查看周期
        </VbenButton>
        <VbenButton
          v-if="canGoCalculate"
          type="primary"
          data-testid="calendar-go-calculate"
          @click="goCalculate"
        >
          去算薪
        </VbenButton>
      </div>
    </template>
  </a-drawer>
</template>
