<script lang="ts" setup>
import type { DashboardRiderRank } from '../../../types/dashboard';

import { useRouter } from 'vue-router';

const props = defineProps<{
  bottom: DashboardRiderRank[];
  top: DashboardRiderRank[];
}>();

const router = useRouter();

const columns = [
  { dataIndex: 'job_no', key: 'job_no', title: '工号', width: 110 },
  { dataIndex: 'name', key: 'name', title: '姓名' },
  { dataIndex: 'order_count', key: 'order_count', title: '单量', width: 80 },
];

function openRider(row: DashboardRiderRank) {
  router.push({
    path: '/rider-salary/calendar',
    query: { rider_id: String(row.rider_id) },
  });
}
</script>

<template>
  <div
    v-if="top.length || bottom.length"
    class="grid grid-cols-1 gap-3 lg:grid-cols-2"
  >
    <a-card v-if="top.length" size="small" title="单量 Top 10">
      <a-table
        :columns="columns"
        :custom-row="(record: DashboardRiderRank) => ({
          onClick: () => openRider(record),
          style: { cursor: 'pointer' },
        })"
        :data-source="top"
        :pagination="false"
        row-key="rider_id"
        size="small"
      />
    </a-card>
    <a-card v-if="bottom.length" size="small" title="低产 5 名">
      <a-table
        :columns="columns"
        :custom-row="(record: DashboardRiderRank) => ({
          onClick: () => openRider(record),
          style: { cursor: 'pointer' },
        })"
        :data-source="bottom"
        :pagination="false"
        row-key="rider_id"
        size="small"
      />
    </a-card>
  </div>
</template>
