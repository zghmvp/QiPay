<script lang="ts" setup>
import type { DashboardAttentionBlock } from '../../../types/dashboard';

import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';

import { useAccess } from '@vben/access';
import { confirm } from '@vben/common-ui';

import { message } from 'antdv-next';

import { calculatePeriodApi } from '../../../api/period';
import MoneyText from '../../../components/MoneyText.vue';
import StatusTag from '../../../components/StatusTag.vue';
import {
  ORDER_STATUS_OPTIONS,
  PERIOD_STATUS_OPTIONS,
} from '../../../constants/enums';
import { toDateTimeString } from '../../../utils/date';

const props = defineProps<{
  blocks: DashboardAttentionBlock[];
}>();

const emit = defineEmits<{
  refreshed: [];
}>();

const router = useRouter();
const { hasAccessByCodes } = useAccess();
const recalculating = ref<null | number>(null);

const visible = computed(() =>
  props.blocks.filter((block) => block.count > 0),
);

const canCalculate = computed(() =>
  hasAccessByCodes(['rs:period:calculate']),
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
        { dataIndex: 'days_left', key: 'days_left', title: '剩余天数', width: 110 },
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

function rowLink(block: DashboardAttentionBlock, record: Record<string, unknown>) {
  if (typeof record.link === 'string' && record.link) return record.link;
  switch (block.key) {
    case 'abnormal_orders':
      return block.link;
    case 'due_periods':
    case 'stale_periods': {
      const id = Number(record.period_id);
      return Number.isFinite(id) && id > 0
        ? `/rider-salary/period?id=${id}`
        : block.link;
    }
    case 'import_gaps': {
      const siteId = Number(record.site_id);
      const date = String(record.date ?? '');
      const params = new URLSearchParams();
      if (Number.isFinite(siteId) && siteId > 0)
        params.set('site_id', String(siteId));
      if (date) params.set('date', date);
      const qs = params.toString();
      return qs ? `/rider-salary/order?${qs}` : block.link;
    }
    case 'no_plan_days': {
      const riderId = Number(record.rider_id);
      return Number.isFinite(riderId) && riderId > 0
        ? `/rider-salary/rider?rider_id=${riderId}&tab=binding`
        : block.link;
    }
    case 'pending_advances':
      return '/rider-salary/advance?status=pending';
    case 'resigned_with_orders': {
      const riderId = Number(record.rider_id);
      return Number.isFinite(riderId) && riderId > 0
        ? `/rider-salary/rider?rider_id=${riderId}`
        : block.link;
    }
    default:
      return block.link;
  }
}

function go(link: string) {
  const { path, query } = parseLink(link);
  void router.push({ path, query });
}

function onRowClick(block: DashboardAttentionBlock, record: Record<string, unknown>) {
  go(rowLink(block, record));
}

async function onRecalculate(
  event: Event,
  record: Record<string, unknown>,
) {
  event.stopPropagation();
  const periodId = Number(record.period_id);
  if (!Number.isFinite(periodId) || periodId <= 0) return;
  try {
    await confirm({
      content: `确认立即重算周期「${String(record.range ?? periodId)}」？将按当前数据重新计算该周期内骑手薪资。`,
      icon: 'warning',
    });
  } catch {
    return;
  }
  recalculating.value = periodId;
  try {
    const res = await calculatePeriodApi(periodId, {});
    const failedCount = res.failed?.length ?? 0;
    if (res.queued) {
      message.info('算薪已转入后台处理');
    } else if (failedCount > 0) {
      const detail = (res.failed ?? [])
        .map((row) => {
          const who = row.job_no ? `工号 ${row.job_no}` : `骑手 #${row.rider_id}`;
          return `${who}：${(row.errors ?? []).join('；')}`;
        })
        .join('；');
      message.error(
        `算薪部分失败：成功 ${res.calculated} 人，失败 ${failedCount} 人。${detail}`,
      );
    } else {
      message.success(`已计算 ${res.calculated} 名骑手`);
    }
    emit('refreshed');
  } finally {
    recalculating.value = null;
  }
}

function daysLeftText(value: unknown) {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  if (n < 0) return `逾期 ${Math.abs(n)} 天`;
  if (n === 0) return '今日到期';
  return `${n} 天`;
}
</script>

<template>
  <div v-if="visible.length" class="flex flex-col gap-2">
    <div class="text-base font-medium">待处理事项</div>
    <a-collapse>
      <a-collapse-panel v-for="block in visible" :key="block.key">
        <template #header>
          <span>{{ block.title }}</span>
          <a-badge :count="block.count" class="ml-2" />
        </template>
        <a-table
          :columns="columns(block.key)"
          :custom-row="
            (record: Record<string, unknown>) => ({
              class: 'cursor-pointer',
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
            <span v-else-if="column.key === 'days_left'">
              {{ daysLeftText(record.days_left) }}
            </span>
            <span
              v-else-if="column.key === 'action' && block.key === 'stale_periods'"
              @click.stop
            >
              <a-button
                v-if="canCalculate"
                size="small"
                type="link"
                :loading="recalculating === Number(record.period_id)"
                @click="(e: Event) => onRecalculate(e, record)"
              >
                立即重算
              </a-button>
              <span v-else class="text-muted-foreground text-xs">无权限</span>
            </span>
          </template>
        </a-table>
        <div class="mt-2 text-right">
          <a-button type="link" @click="go(block.link)">查看全部</a-button>
        </div>
      </a-collapse-panel>
    </a-collapse>
  </div>
</template>
