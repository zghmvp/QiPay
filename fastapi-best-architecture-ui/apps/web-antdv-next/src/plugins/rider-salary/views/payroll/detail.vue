<script lang="ts" setup>
import type {
  PayrollDetailItem,
  PayrollGroupedDetail,
  SubjectBreakdownItem,
} from '../../types/payroll';

import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { VbenButton } from '@vben/common-ui';

import { getPayrollApi } from '../../api/payroll';
import MoneyText from '../../components/MoneyText.vue';
import StatusTag from '../../components/StatusTag.vue';
import {
  CYCLE_TYPE_OPTIONS,
  DAY_STATUS_OPTIONS,
  DETAIL_SOURCE_OPTIONS,
  enumLabel,
  PAYROLL_KIND_OPTIONS,
  PAYROLL_STATUS_OPTIONS,
  PERIOD_STATUS_OPTIONS,
  SUBJECT_DIRECTION_OPTIONS,
} from '../../constants/enums';
import { toDateTimeString } from '../../utils/date';
import PageContainer from '../_shared/PageContainer.vue';

const route = useRoute();
const router = useRouter();

const loading = ref(false);
const detail = ref<PayrollGroupedDetail>();
const loadError = ref('');
const activeTab = ref('daily');
const subjectFilter = ref<null | number>(null);

const payrollId = computed(() => Number(route.params.id));

const riderLabel = computed(() => {
  const d = detail.value;
  if (!d) return '';
  return [d.rider_job_no || d.job_no, d.rider_name].filter(Boolean).join(' ');
});

const filteredDetails = computed(() => {
  const grouped = detail.value?.details ?? {};
  const rows = Object.values(grouped).flat();
  if (subjectFilter.value == null) return rows;
  return rows.filter((row) => row.subject_id === subjectFilter.value);
});

const detailColumns = [
  { dataIndex: 'biz_date', title: '日期', width: 110 },
  { dataIndex: 'name', key: 'name', title: '项名称' },
  { dataIndex: 'subject_name', key: 'subject', title: '科目', width: 120 },
  { dataIndex: 'order_no', key: 'order_no', title: '订单号', width: 150 },
  { dataIndex: 'source', key: 'source', title: '来源', width: 90 },
  { dataIndex: 'amount', key: 'amount', title: '金额', width: 110 },
];

const dailyColumns = [
  { dataIndex: 'biz_date', key: 'biz_date', title: '日期', width: 120 },
  { dataIndex: 'order_count', key: 'order_count', title: '单量', width: 80 },
  { dataIndex: 'valid_order_count', title: '有效', width: 80 },
  { dataIndex: 'formula_amount', key: 'formula_amount', title: '公式' },
  { dataIndex: 'manual_bonus', key: 'manual_bonus', title: '奖' },
  { dataIndex: 'manual_penalty', key: 'manual_penalty', title: '惩' },
  { dataIndex: 'net_adjust', key: 'net_adjust', title: '净' },
  { dataIndex: 'day_status', key: 'day_status', title: '日状态', width: 110 },
];

const breakdownColumns = [
  { dataIndex: 'subject_name', title: '科目名' },
  { dataIndex: 'direction', key: 'direction', title: '方向', width: 90 },
  {
    dataIndex: 'include_in_gross',
    key: 'include_in_gross',
    title: '进应发',
    width: 80,
  },
  { dataIndex: 'line_count', title: '笔数', width: 70 },
  { dataIndex: 'amount_sum', key: 'amount_sum', title: '合计金额', width: 120 },
];

const advanceColumns = [
  { dataIndex: 'advance_id', key: 'advance_id', title: '预支单ID', width: 110 },
  { dataIndex: 'amount', key: 'amount', title: '抵扣额', width: 110 },
  {
    dataIndex: 'remaining_after',
    key: 'remaining_after',
    title: '抵扣后剩余',
    width: 120,
  },
  { dataIndex: 'deduct_status', title: '状态', width: 100 },
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

function q(extra: Record<string, string | number | undefined>) {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(extra)) {
    if (v === undefined || v === null || v === '') continue;
    out[k] = String(v);
  }
  return out;
}

function goOrder(extra: Record<string, string | number | undefined>) {
  const d = detail.value;
  router.push({
    path: '/rider-salary/order',
    query: q({
      site_id: d?.site_id ?? undefined,
      rider_id: d?.rider_id,
      ...extra,
    }),
  });
}

function goAdjustment(extra: Record<string, string | number | undefined>) {
  const d = detail.value;
  router.push({
    path: '/rider-salary/adjustment',
    query: q({
      site_id: d?.site_id ?? undefined,
      rider_id: d?.rider_id,
      date_from: d?.period_start ?? undefined,
      date_to: d?.period_end ?? undefined,
      ...extra,
    }),
  });
}

function goAdvance(advanceId?: null | number) {
  const d = detail.value;
  router.push({
    path: '/rider-salary/advance',
    query: q({
      id: advanceId ?? undefined,
      site_id: d?.site_id ?? undefined,
      rider_id: d?.rider_id,
    }),
  });
}

function goPeriod(stale?: boolean) {
  const d = detail.value;
  if (!d) return;
  if (stale) {
    router.push({
      path: `/rider-salary/period/${d.period_id}/calculate`,
    });
    return;
  }
  router.push({
    path: '/rider-salary/period',
    query: q({
      id: d.period_id,
    }),
  });
}

function goCalendar() {
  const d = detail.value;
  if (!d?.period_start) return;
  router.push({
    path: '/rider-salary/calendar',
    query: q({
      site_id: d.site_id ?? undefined,
      rider_id: d.rider_id,
      month: d.period_start.slice(0, 7),
    }),
  });
}

function goBinding() {
  const d = detail.value;
  if (!d) return;
  router.push({
    path: `/rider-salary/rider/${d.rider_id}`,
    query: { tab: 'binding' },
  });
}

function onBreakdownClick(row: SubjectBreakdownItem) {
  const sources = row.sources || [];
  if (sources.includes('manual')) {
    goAdjustment({ subject_id: row.subject_id ?? undefined });
    return;
  }
  if (sources.includes('advance')) {
    goAdvance();
    return;
  }
  subjectFilter.value = row.subject_id ?? null;
  activeTab.value = 'details';
  router.replace({
    query: {
      ...route.query,
      tab: 'details',
      subject_id:
        row.subject_id != null ? String(row.subject_id) : undefined,
    },
  });
}

function onDetailLink(row: PayrollDetailItem, kind: 'order' | 'manual' | 'date') {
  if (kind === 'order' && row.order_no) {
    goOrder({ order_no: row.order_no });
    return;
  }
  if (kind === 'date' && row.biz_date) {
    goOrder({ date_from: row.biz_date, date_to: row.biz_date });
    return;
  }
  if (kind === 'manual') {
    goAdjustment({
      subject_id: row.subject_id,
      id: row.adjustment_id ?? undefined,
      date_from: row.biz_date ?? detail.value?.period_start ?? undefined,
      date_to: row.biz_date ?? detail.value?.period_end ?? undefined,
    });
  }
}

function clearSubjectFilter() {
  subjectFilter.value = null;
  const next = { ...route.query };
  delete next.subject_id;
  router.replace({ query: next });
}

async function load() {
  if (!Number.isFinite(payrollId.value) || payrollId.value <= 0) {
    loadError.value = '无效的薪资单 ID';
    detail.value = undefined;
    return;
  }
  loading.value = true;
  loadError.value = '';
  try {
    detail.value = await getPayrollApi(payrollId.value);
  } catch (error: unknown) {
    detail.value = undefined;
    const msg =
      (error as { message?: string; response?: { data?: { msg?: string } } })
        ?.response?.data?.msg ||
      (error as Error)?.message ||
      '加载失败';
    loadError.value =
      msg.includes('不存在') || msg.includes('404')
        ? '该薪资单不存在：可能尚未计算成功，或计算失败未落库。请到结算周期查看失败面板后重算。'
        : msg;
  } finally {
    loading.value = false;
  }
}

watch(activeTab, (tab) => {
  router.replace({ query: { ...route.query, tab } });
});

watch(payrollId, () => {
  void load();
});

onMounted(() => {
  const tab = route.query.tab;
  if (tab === 'details' || tab === 'daily' || tab === 'advance') {
    activeTab.value = String(tab);
  }
  const sid = Number(route.query.subject_id);
  if (Number.isFinite(sid) && sid > 0) {
    subjectFilter.value = sid;
    activeTab.value = 'details';
  }
  void load();
});
</script>

<template>
  <PageContainer>
    <a-spin :spinning="loading">
      <div class="mb-4 flex flex-wrap items-center gap-3">
        <VbenButton data-testid="payroll-back" @click="router.back()">
          ← 返回
        </VbenButton>
        <h2 class="m-0 text-lg font-medium" data-testid="payroll-detail-title">
          薪资明细
          <span v-if="riderLabel"> · {{ riderLabel }}</span>
        </h2>
        <div class="ml-auto flex flex-wrap gap-2">
          <VbenButton
            v-if="detail"
            data-testid="payroll-open-period"
            @click="goPeriod()"
          >
            打开周期
          </VbenButton>
          <VbenButton
            v-if="detail"
            data-testid="payroll-open-calendar"
            @click="goCalendar"
          >
            打开日历
          </VbenButton>
        </div>
      </div>

      <a-alert
        v-if="loadError"
        class="mb-4"
        type="error"
        show-icon
        :message="loadError"
      >
        <template #action>
          <VbenButton size="small" @click="goPeriod()">去周期</VbenButton>
        </template>
      </a-alert>

      <template v-if="detail">
        <a-alert
          v-if="detail.stale"
          class="mb-4"
          type="error"
          show-icon
          message="数据已变更，需重算后结果才可信"
          description="明细只读展示，金额可能已过期。"
          data-testid="payroll-stale-banner"
        >
          <template #action>
            <VbenButton
              type="primary"
              danger
              size="small"
              data-testid="payroll-recalc-cta"
              @click="goPeriod(true)"
            >
              去算薪页重算
            </VbenButton>
          </template>
        </a-alert>

        <a-alert
          v-if="detail.warnings?.length"
          class="mb-4"
          type="warning"
          show-icon
          message="次要提示（非金额硬失败）"
          :description="detail.warnings.join('；')"
        />

        <a-card class="mb-4" size="small" data-testid="payroll-summary">
          <a-descriptions bordered size="small" :column="{ xs: 1, sm: 2, md: 3 }">
            <a-descriptions-item label="站点">
              {{ detail.site_name || '—' }}
            </a-descriptions-item>
            <a-descriptions-item label="周期">
              {{ detail.period_start }} ~ {{ detail.period_end }}
            </a-descriptions-item>
            <a-descriptions-item label="周期类型">
              <StatusTag
                :options="CYCLE_TYPE_OPTIONS"
                :value="detail.cycle_type"
              />
            </a-descriptions-item>
            <a-descriptions-item label="周期状态">
              <StatusTag
                :options="PERIOD_STATUS_OPTIONS"
                :value="detail.period_status"
              />
            </a-descriptions-item>
            <a-descriptions-item label="单据类型">
              <StatusTag
                :options="PAYROLL_KIND_OPTIONS"
                :value="detail.kind"
              />
            </a-descriptions-item>
            <a-descriptions-item label="状态">
              <StatusTag
                :options="PAYROLL_STATUS_OPTIONS"
                :value="detail.status"
              />
            </a-descriptions-item>
            <a-descriptions-item label="轮次">
              {{ detail.calc_version }}
            </a-descriptions-item>
            <a-descriptions-item label="需重算">
              <a-tag :color="detail.stale ? 'error' : 'default'">
                {{ detail.stale ? '是' : '否' }}
              </a-tag>
            </a-descriptions-item>
            <a-descriptions-item label="单量">
              <a
                class="cursor-pointer text-primary"
                data-testid="payroll-order-count-link"
                @click="
                  goOrder({
                    date_from: detail.period_start ?? undefined,
                    date_to: detail.period_end ?? undefined,
                  })
                "
              >
                {{ detail.order_count }} / 有效 {{ detail.valid_order_count }}
              </a>
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
            <a-descriptions-item label="计算时间">
              {{ toDateTimeString(detail.calc_time) || '—' }}
            </a-descriptions-item>
            <a-descriptions-item
              v-if="detail.plan_version_labels?.length"
              label="方案版本"
            >
              {{
                detail.plan_version_labels
                  .map((item) => item.name || item.code || item.id)
                  .join('、')
              }}
            </a-descriptions-item>
          </a-descriptions>
        </a-card>

        <a-card class="mb-4" size="small" title="科目汇总">
          <a-table
            size="small"
            :columns="breakdownColumns"
            :data-source="detail.subject_breakdown"
            :pagination="false"
            :row-key="
              (row: SubjectBreakdownItem) =>
                `${row.subject_id}-${row.include_in_gross}-${row.subject_name}`
            "
            :custom-row="
              (row: SubjectBreakdownItem) => ({
                onClick: () => onBreakdownClick(row),
                style: { cursor: 'pointer' },
              })
            "
            data-testid="payroll-subject-breakdown"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'direction'">
                {{
                  enumLabel(SUBJECT_DIRECTION_OPTIONS, record.direction) || '—'
                }}
              </template>
              <template v-else-if="column.key === 'include_in_gross'">
                {{ record.include_in_gross ? '是' : '否' }}
              </template>
              <template v-else-if="column.key === 'amount_sum'">
                <MoneyText :value="record.amount_sum" signed />
              </template>
            </template>
          </a-table>
        </a-card>

        <a-tabs v-model:active-key="activeTab" data-testid="payroll-detail-tabs">
          <a-tab-pane key="daily" tab="按日">
            <a-table
              size="small"
              :columns="dailyColumns"
              :data-source="detail.dailies"
              :pagination="false"
              row-key="biz_date"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'biz_date'">
                  <a
                    class="cursor-pointer text-primary"
                    @click="
                      goOrder({
                        date_from: record.biz_date,
                        date_to: record.biz_date,
                      })
                    "
                  >
                    {{ record.biz_date }}
                  </a>
                </template>
                <template v-else-if="column.key === 'order_count'">
                  <a
                    class="cursor-pointer text-primary"
                    @click="
                      goOrder({
                        date_from: record.biz_date,
                        date_to: record.biz_date,
                      })
                    "
                  >
                    {{ record.order_count }}
                  </a>
                </template>
                <template v-else-if="column.key === 'formula_amount'">
                  <MoneyText :value="record.formula_amount" />
                </template>
                <template v-else-if="column.key === 'manual_bonus'">
                  <MoneyText :value="record.manual_bonus" />
                </template>
                <template v-else-if="column.key === 'manual_penalty'">
                  <MoneyText :value="record.manual_penalty" />
                </template>
                <template v-else-if="column.key === 'net_adjust'">
                  <MoneyText :value="record.net_adjust" signed />
                </template>
                <template v-else-if="column.key === 'day_status'">
                  <div class="flex items-center gap-2">
                    <StatusTag
                      :options="DAY_STATUS_OPTIONS"
                      :value="record.day_status"
                    />
                    <a
                      v-if="record.day_status === 'no_plan'"
                      class="cursor-pointer text-primary"
                      @click="goBinding"
                    >
                      去绑方案
                    </a>
                  </div>
                </template>
              </template>
            </a-table>
          </a-tab-pane>

          <a-tab-pane key="details" tab="阶段明细">
            <div v-if="subjectFilter != null" class="mb-2">
              <a-tag closable @close="clearSubjectFilter">
                已筛选科目 ID {{ subjectFilter }}
              </a-tag>
            </div>
            <a-table
              size="small"
              :columns="detailColumns"
              :data-source="filteredDetails"
              :pagination="{ pageSize: 50 }"
              :row-key="(row: PayrollDetailItem) => row.id ?? `${row.stage}-${row.order_id}-${row.amount}`"
              data-testid="payroll-stage-details"
            >
              <template #expandedRowRender="{ record }">
                <pre class="m-0 whitespace-pre-wrap text-xs">{{
                  formatTrace(record.calc_trace)
                }}</pre>
              </template>
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'order_no'">
                  <a
                    v-if="record.order_no"
                    class="cursor-pointer text-primary"
                    @click="onDetailLink(record, 'order')"
                  >
                    {{ record.order_no }}
                  </a>
                  <span v-else>—</span>
                </template>
                <template v-else-if="column.key === 'subject'">
                  <a
                    v-if="record.source === 'manual'"
                    class="cursor-pointer text-primary"
                    @click="onDetailLink(record, 'manual')"
                  >
                    {{ record.subject_name || record.name || record.subject_id }}
                  </a>
                  <span v-else>
                    {{ record.subject_name || record.name || '—' }}
                  </span>
                </template>
                <template v-else-if="column.key === 'source'">
                  <StatusTag
                    :options="DETAIL_SOURCE_OPTIONS"
                    :value="record.source"
                  />
                </template>
                <template v-else-if="column.key === 'amount'">
                  <MoneyText :value="record.amount" signed />
                </template>
                <template v-else-if="column.key === 'name'">
                  <a
                    v-if="record.biz_date"
                    class="cursor-pointer text-primary"
                    @click="onDetailLink(record, 'date')"
                  >
                    {{ record.plan_item_name || record.name || '—' }}
                  </a>
                  <span v-else>
                    {{ record.plan_item_name || record.name || '—' }}
                  </span>
                </template>
              </template>
            </a-table>
          </a-tab-pane>

          <a-tab-pane key="advance" tab="预支抵扣">
            <a-table
              size="small"
              :columns="advanceColumns"
              :data-source="detail.advance_lines"
              :pagination="false"
              :row-key="(row) => row.advance_id"
              data-testid="payroll-advance-lines"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'advance_id'">
                  <a
                    class="cursor-pointer text-primary"
                    @click="goAdvance(record.advance_id)"
                  >
                    {{ record.advance_id }}
                  </a>
                </template>
                <template v-else-if="column.key === 'amount'">
                  <MoneyText :value="record.amount" />
                </template>
                <template v-else-if="column.key === 'remaining_after'">
                  <MoneyText
                    v-if="record.remaining_after != null"
                    :value="record.remaining_after"
                  />
                  <span v-else>—</span>
                </template>
              </template>
            </a-table>
            <a-empty
              v-if="!detail.advance_lines?.length"
              description="本期无预支抵扣"
            />
          </a-tab-pane>
        </a-tabs>
      </template>
    </a-spin>
  </PageContainer>
</template>
