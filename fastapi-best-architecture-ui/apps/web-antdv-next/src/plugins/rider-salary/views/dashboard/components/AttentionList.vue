<script lang="ts" setup>
import type { DashboardAttentionBlock } from '../../../types/dashboard';

import { computed } from 'vue';
import { useRouter } from 'vue-router';

import { useAccess } from '@vben/access';

import MoneyText from '../../../components/MoneyText.vue';
import StatusTag from '../../../components/StatusTag.vue';
import {
  ORDER_STATUS_OPTIONS,
  PERIOD_STATUS_OPTIONS,
} from '../../../constants/enums';
import { toDateTimeString } from '../../../utils/date';
import {
  daysLeftOf,
  dueCountdownText,
  isDueCountdownItem,
  isOverdueUnlocked,
  LOCK_COUNTDOWN_TITLE,
} from '../due-countdown';
import {
  abnormalAttentionTarget,
  lockCountdownViewAllTarget,
  noPlanBindingTarget,
  noPlanViewAllTarget,
  pendingAdvanceRowTarget,
  pendingAdvancesViewAllTarget,
  stalePeriodCalcTarget,
  stalePeriodsViewAllTarget,
} from '../scope-links';

const props = defineProps<{
  blocks: DashboardAttentionBlock[];
  month?: string;
  siteId?: null | number;
}>();

const router = useRouter();
const { hasAccessByCodes } = useAccess();

const canCalculate = computed(() =>
  hasAccessByCodes(['rs:period:calculate']),
);

function dueItems(block: DashboardAttentionBlock) {
  return (block.items ?? []).filter((record) =>
    isDueCountdownItem(daysLeftOf(record)),
  );
}

const visible = computed(() =>
  props.blocks
    .map((block) => {
      if (block.key !== 'due_periods') return block;
      const items = dueItems(block);
      return {
        ...block,
        count: items.length,
        items,
        title: LOCK_COUNTDOWN_TITLE,
      };
    })
    .filter((block) => block.count > 0),
);

function columns(key: string) {
  switch (key) {
    case 'abnormal_orders':
      return [
        { dataIndex: 'order_no', key: 'order_no', title: '订单号' },
        { dataIndex: 'rider_name', key: 'rider_name', title: '骑手' },
        { dataIndex: 'status', key: 'status', title: '状态', width: 100 },
        {
          dataIndex: 'duration_min',
          key: 'duration_min',
          title: '时长(分)',
          width: 100,
        },
      ];
    case 'due_periods':
      return [
        { dataIndex: 'range', key: 'range', title: '周期' },
        { dataIndex: 'status', key: 'status', title: '状态', width: 90 },
        { dataIndex: 'end_date', key: 'end_date', title: '结束日', width: 120 },
        { dataIndex: 'days_left', key: 'days_left', title: '倒计时', width: 140 },
      ];
    case 'import_gaps':
      return [
        { dataIndex: 'site_name', key: 'site_name', title: '站点' },
        { dataIndex: 'date', key: 'date', title: '缺口日期' },
      ];
    case 'no_plan_days':
      return [
        { dataIndex: 'job_no', key: 'job_no', title: '工号' },
        { dataIndex: 'name', key: 'name', title: '姓名' },
        { dataIndex: 'count', key: 'count', title: '无方案天数', width: 110 },
      ];
    case 'pending_advances':
      return [
        { dataIndex: 'rider_name', key: 'rider_name', title: '骑手' },
        { dataIndex: 'amount', key: 'amount', title: '金额', width: 110 },
        { dataIndex: 'submit_time', key: 'submit_time', title: '提交时间' },
      ];
    case 'resigned_with_orders':
      return [
        { dataIndex: 'job_no', key: 'job_no', title: '工号' },
        { dataIndex: 'name', key: 'name', title: '姓名' },
        {
          dataIndex: 'order_count',
          key: 'order_count',
          title: '本月单量',
          width: 100,
        },
      ];
    case 'stale_periods':
      return [
        { dataIndex: 'range', key: 'range', title: '周期' },
        { dataIndex: 'status', key: 'status', title: '状态', width: 90 },
        { dataIndex: 'stale_count', key: 'stale_count', title: '需重算', width: 90 },
        {
          dataIndex: 'action',
          key: 'action',
          title: '操作',
          width: 110,
        },
      ];
    default:
      return [{ dataIndex: 'title', key: 'title', title: '条目' }];
  }
}

function parseLink(link: string) {
  try {
    const url = new URL(link, window.location.origin);
    const query: Record<string, string> = {};
    url.searchParams.forEach((value, key) => {
      query[key] = value;
    });
    return { path: url.pathname, query };
  } catch {
    return { path: link, query: {} };
  }
}

function viewAllLink(block: DashboardAttentionBlock) {
  if (block.key === 'abnormal_orders') {
    return abnormalAttentionTarget(props.siteId, props.month);
  }
  if (block.key === 'due_periods') {
    return lockCountdownViewAllTarget(props.siteId);
  }
  if (block.key === 'no_plan_days') {
    const first = block.items[0];
    const siteId =
      props.siteId ??
      (first ? Number(first.site_id) : undefined);
    const month =
      props.month ||
      (first ? String(first.month ?? '') : undefined);
    return noPlanViewAllTarget(siteId, month);
  }
  if (block.key === 'stale_periods') {
    return stalePeriodsViewAllTarget(props.siteId, props.month);
  }
  if (block.key === 'pending_advances') {
    return pendingAdvancesViewAllTarget(props.siteId, props.month);
  }
  return parseLink(block.link);
}

function rowLink(
  block: DashboardAttentionBlock,
  record: Record<string, unknown>,
) {
  if (block.key === 'abnormal_orders') {
    const orderNo = String(record.order_no ?? '');
    return abnormalAttentionTarget(
      props.siteId ?? Number(record.site_id) ?? undefined,
      props.month,
      orderNo || undefined,
    );
  }
  if (block.key === 'due_periods') {
    const id = Number(record.period_id);
    if (Number.isFinite(id) && id > 0) {
      return { path: '/rider-salary/period', query: { id: String(id) } };
    }
  }
  if (block.key === 'stale_periods') {
    const id = Number(record.period_id);
    if (Number.isFinite(id) && id > 0) {
      return stalePeriodCalcTarget(id);
    }
  }
  if (block.key === 'no_plan_days') {
    const riderId = Number(record.rider_id);
    if (Number.isFinite(riderId) && riderId > 0) {
      return noPlanBindingTarget(
        riderId,
        props.siteId ?? Number(record.site_id) ?? undefined,
        props.month || String(record.month ?? '') || undefined,
      );
    }
  }
  if (block.key === 'pending_advances') {
    const id = Number(record.id);
    if (Number.isFinite(id) && id > 0) {
      return pendingAdvanceRowTarget(id, props.siteId, props.month);
    }
    return pendingAdvancesViewAllTarget(props.siteId, props.month);
  }
  if (typeof record.link === 'string' && record.link) {
    return parseLink(record.link);
  }
  switch (block.key) {
    case 'import_gaps': {
      const siteId = Number(record.site_id);
      const date = String(record.date ?? '');
      const query: Record<string, string> = {};
      if (Number.isFinite(siteId) && siteId > 0) query.site_id = String(siteId);
      if (date) query.date = date;
      return { path: '/rider-salary/order', query };
    }
    case 'pending_advances': {
      const id = Number(record.id);
      if (Number.isFinite(id) && id > 0) {
        return pendingAdvanceRowTarget(id, props.siteId, props.month);
      }
      return pendingAdvancesViewAllTarget(props.siteId, props.month);
    }
    case 'resigned_with_orders': {
      const riderId = Number(record.rider_id);
      return Number.isFinite(riderId) && riderId > 0
        ? {
            path: '/rider-salary/rider',
            query: { rider_id: String(riderId) },
          }
        : parseLink(block.link);
    }
    default:
      return parseLink(block.link);
  }
}

function go(target: { path: string; query: Record<string, string> } | string) {
  if (typeof target === 'string') {
    const parsed = parseLink(target);
    void router.push(parsed);
    return;
  }
  void router.push(target);
}

function onRowClick(
  block: DashboardAttentionBlock,
  record: Record<string, unknown>,
) {
  go(rowLink(block, record));
}

function onRecalculate(event: Event, record: Record<string, unknown>) {
  event.stopPropagation();
  const periodId = Number(record.period_id);
  if (!Number.isFinite(periodId) || periodId <= 0) return;
  void router.push({
    path: `/rider-salary/period/${periodId}/calculate`,
  });
}

function blockTestId(key: string) {
  if (key === 'abnormal_orders') return 'ops-dashboard-abnormal-attention-landing';
  if (key === 'due_periods') return 'ops-dashboard-lock-overdue-visible';
  if (key === 'no_plan_days') return 'ops-dashboard-no-plan-to-binding';
  if (key === 'stale_periods') return 'ops-dashboard-stale-to-calc';
  return `dashboard-attention-${key}`;
}

function viewAllTestId(key: string) {
  if (key === 'abnormal_orders') return 'dashboard-abnormal-view-all';
  if (key === 'due_periods') return 'dashboard-lock-view-all';
  if (key === 'no_plan_days') return 'dashboard-no-plan-view-all';
  if (key === 'stale_periods') return 'dashboard-stale-view-all';
  if (key === 'pending_advances') return 'dashboard-advance-view-all';
  return undefined;
}

function rowTestId(key: string) {
  if (key === 'no_plan_days') return 'dashboard-no-plan-row';
  if (key === 'stale_periods') return 'dashboard-stale-row';
  if (key === 'pending_advances') return 'dashboard-advance-row';
  return undefined;
}
</script>

<template>
  <div v-if="visible.length" class="flex flex-col gap-2">
    <div class="text-base font-medium">待处理事项</div>
    <a-collapse>
      <a-collapse-panel
        v-for="block in visible"
        :key="block.key"
        :data-testid="blockTestId(block.key)"
      >
        <template #header>
          <span
            :data-testid="
              block.key === 'due_periods' ? 'dashboard-lock-title' : undefined
            "
          >{{ block.title }}</span>
          <a-badge :count="block.count" class="ml-2" />
        </template>
        <a-table
          :columns="columns(block.key)"
          :on-row="
            (record: Record<string, unknown>) => ({
              class: 'cursor-pointer',
              'data-advance-id': record.id,
              'data-period-id': record.period_id,
              'data-rider-id': record.rider_id,
              'data-testid': rowTestId(block.key),
              onClick: () => onRowClick(block, record),
            })
          "
          :data-source="block.items"
          :pagination="false"
          :row-key="
            (record: Record<string, unknown>, index: number) =>
              String(
                record.period_id ??
                  record.id ??
                  record.rider_id ??
                  record.date ??
                  index,
              )
          "
          size="small"
        >
          <template #bodyCell="{ column, record }">
            <StatusTag
              v-if="column.key === 'status' && block.key !== 'abnormal_orders'"
              :options="PERIOD_STATUS_OPTIONS"
              :value="String(record.status ?? '')"
            />
            <StatusTag
              v-else-if="column.key === 'status'"
              :options="ORDER_STATUS_OPTIONS"
              :value="String(record.status ?? '')"
            />
            <MoneyText
              v-else-if="column.key === 'amount'"
              :value="record.amount as string"
            />
            <span v-else-if="column.key === 'submit_time'">
              {{ toDateTimeString(record.submit_time as string) || '—' }}
            </span>
            <span
              v-else-if="column.key === 'days_left'"
              :data-overdue="isOverdueUnlocked(daysLeftOf(record)) ? '1' : '0'"
              :data-testid="
                isOverdueUnlocked(daysLeftOf(record))
                  ? 'dashboard-lock-overdue'
                  : 'dashboard-lock-remaining'
              "
            >
              {{ dueCountdownText(daysLeftOf(record)) }}
            </span>
            <span
              v-else-if="column.key === 'action' && block.key === 'stale_periods'"
              @click.stop
            >
              <a-button
                v-if="canCalculate"
                size="small"
                type="link"
                data-testid="stale-goto-calculate"
                @click="(e: Event) => onRecalculate(e, record)"
              >
                立即重算
              </a-button>
              <span v-else class="text-muted-foreground text-xs">无权限</span>
            </span>
          </template>
        </a-table>
        <div class="mt-2 text-right">
          <a-button
            type="link"
            :data-testid="viewAllTestId(block.key)"
            @click="go(viewAllLink(block))"
          >
            查看全部
          </a-button>
        </div>
      </a-collapse-panel>
    </a-collapse>
  </div>
</template>
