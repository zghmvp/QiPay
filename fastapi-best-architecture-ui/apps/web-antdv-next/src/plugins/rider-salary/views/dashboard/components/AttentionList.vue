<script lang="ts" setup>
import type { DashboardAttentionBlock } from '../../../types/dashboard';

import { computed } from 'vue';
import { useRouter } from 'vue-router';

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

const router = useRouter();

const visible = computed(() =>
  props.blocks.filter((block) => block.count > 0),
);

function periodColumns() {
  return [
    { dataIndex: 'range', key: 'range', title: '周期' },
    { dataIndex: 'status', key: 'status', title: '状态', width: 90 },
    { dataIndex: 'stale_count', key: 'stale_count', title: '需重算', width: 90 },
    { dataIndex: 'days_left', key: 'days_left', title: '剩余天数', width: 90 },
  ];
}

function columns(key: string) {
  switch (key) {
    case 'abnormal_orders':
      return [
        { dataIndex: 'order_no', key: 'order_no', title: '订单号' },
        { dataIndex: 'rider_name', key: 'rider_name', title: '骑手' },
        { dataIndex: 'status', key: 'status', title: '状态', width: 100 },
        { dataIndex: 'duration_min', key: 'duration_min', title: '时长(分)', width: 100 },
      ];
    case 'due_periods':
      return periodColumns();
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
        { dataIndex: 'order_count', key: 'order_count', title: '本月单量', width: 100 },
      ];
    case 'stale_periods':
      return periodColumns();
    default:
      return [
        { dataIndex: 'title', key: 'title', title: '条目' },
      ];
  }
}

function go(link: string) {
  router.push(link);
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
          :data-source="block.items"
          :pagination="false"
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
          </template>
        </a-table>
        <div class="mt-2 text-right">
          <a-button type="link" @click="go(block.link)">查看全部</a-button>
        </div>
      </a-collapse-panel>
    </a-collapse>
  </div>
</template>
