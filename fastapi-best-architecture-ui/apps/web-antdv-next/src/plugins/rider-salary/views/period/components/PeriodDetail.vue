<script lang="ts" setup>
import type { PayrollSummary } from '../../../types/payroll';
import type { PeriodWithPayrolls } from '../../../types/period';

import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';

import { useAccess } from '@vben/access';
import { useVbenDrawer, VbenButton } from '@vben/common-ui';

import { getPeriodApi } from '../../../api/period';
import MoneyText from '../../../components/MoneyText.vue';
import StatusTag from '../../../components/StatusTag.vue';
import {
  CYCLE_TYPE_OPTIONS,
  PAYROLL_KIND_OPTIONS,
  PAYROLL_STATUS_OPTIONS,
  PERIOD_STATUS_OPTIONS,
} from '../../../constants/enums';
import { toDateTimeString } from '../../../utils/date';

const router = useRouter();
const { hasAccessByCodes } = useAccess();
const loading = ref(false);
const detail = ref<PeriodWithPayrolls>();
const canGoCalculate = computed(() => {
  const status = detail.value?.status;
  return (
    (status === 'open' || status === 'reopened') &&
    hasAccessByCodes(['rs:period:calculate'])
  );
});

function goCalculate() {
  const id = detail.value?.id;
  if (!id) return;
  drawerApi.close();
  void router.push({ path: `/rider-salary/period/${id}/calculate` });
}

const columns = [
  { dataIndex: 'job_no', title: '工号', width: 100 },
  { dataIndex: 'rider_name', title: '骑手', width: 100 },
  { dataIndex: 'kind', key: 'kind', title: '单据类型', width: 90 },
  { dataIndex: 'status', key: 'status', title: '状态', width: 90 },
  { dataIndex: 'order_count', title: '单量', width: 70 },
  { dataIndex: 'gross', key: 'gross', title: '应发', width: 100 },
  { dataIndex: 'deduction_total', key: 'deduction', title: '代扣', width: 100 },
  { dataIndex: 'advance_deduction', key: 'advance', title: '预支抵扣', width: 110 },
  { dataIndex: 'net', key: 'net', title: '实发', width: 100 },
  { dataIndex: 'stale', key: 'stale', title: '需重算', width: 80 },
  { dataIndex: 'calc_time', key: 'calc_time', title: '计算时间', width: 170 },
];

function openPayroll(row: PayrollSummary) {
  router.push({ path: `/rider-salary/payroll/${row.id}` });
}

const [Drawer, drawerApi] = useVbenDrawer({
  class: 'w-[960px]',
  cancelText: '关闭',
  destroyOnClose: true,
  showConfirmButton: false,
  async onOpenChange(isOpen) {
    if (!isOpen) return;
    const pk = drawerApi.getData<{ id?: number }>()?.id;
    detail.value = undefined;
    if (!pk) return;
    loading.value = true;
    try {
      detail.value = await getPeriodApi(pk);
    } finally {
      loading.value = false;
    }
  },
});
</script>

<template>
  <Drawer title="周期详情">
    <a-spin :spinning="loading">
      <template v-if="detail">
        <a-descriptions bordered size="small" :column="3" class="mb-4">
          <a-descriptions-item label="站点">{{ detail.site_name || '—' }}</a-descriptions-item>
          <a-descriptions-item label="骑手">
            {{
              detail.rider_id
                ? [detail.rider_job_no, detail.rider_name].filter(Boolean).join(' ')
                : '—'
            }}
          </a-descriptions-item>
          <a-descriptions-item label="类型">
            <StatusTag :options="CYCLE_TYPE_OPTIONS" :value="detail.cycle_type" />
          </a-descriptions-item>
          <a-descriptions-item label="区间">
            {{ detail.start_date }} ~ {{ detail.end_date }}
          </a-descriptions-item>
          <a-descriptions-item label="状态">
            <StatusTag :options="PERIOD_STATUS_OPTIONS" :value="detail.status" />
          </a-descriptions-item>
          <a-descriptions-item label="需重算">
            <span :class="detail.stale_count ? 'font-medium text-red-500' : ''">
              {{ detail.stale_count ?? 0 }}
            </span>
          </a-descriptions-item>
          <a-descriptions-item label="应发合计">
            <MoneyText :value="detail.gross_total" />
          </a-descriptions-item>
          <a-descriptions-item label="实发合计">
            <MoneyText :value="detail.net_total" />
          </a-descriptions-item>
          <a-descriptions-item label="锁账时间">
            {{ toDateTimeString(detail.locked_time) || '—' }}
          </a-descriptions-item>
        </a-descriptions>
        <a-table
          size="small"
          data-testid="period-payroll-table"
          :columns="columns"
          :data-source="detail.payrolls"
          :pagination="false"
          :row-key="(row: PayrollSummary) => row.id"
          :custom-row="(row: PayrollSummary) => ({
            onClick: () => openPayroll(row),
            style: { cursor: 'pointer' },
          })"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'kind'">
              <StatusTag :options="PAYROLL_KIND_OPTIONS" :value="record.kind" />
            </template>
            <template v-else-if="column.key === 'status'">
              <StatusTag :options="PAYROLL_STATUS_OPTIONS" :value="record.status" />
            </template>
            <template v-else-if="column.key === 'gross'">
              <MoneyText :value="record.gross" />
            </template>
            <template v-else-if="column.key === 'deduction'">
              <MoneyText :value="record.deduction_total" />
            </template>
            <template v-else-if="column.key === 'advance'">
              <MoneyText :value="record.advance_deduction" />
            </template>
            <template v-else-if="column.key === 'net'">
              <MoneyText :value="record.net" />
            </template>
            <template v-else-if="column.key === 'stale'">
              <span :class="record.stale ? 'font-medium text-red-500' : ''">
                {{ record.stale ? '是' : '否' }}
              </span>
            </template>
            <template v-else-if="column.key === 'calc_time'">
              {{ toDateTimeString(record.calc_time) || '—' }}
            </template>
          </template>
        </a-table>
        <div v-if="canGoCalculate" class="mt-4 text-right">
          <VbenButton
            type="primary"
            data-testid="period-detail-go-calculate"
            @click="goCalculate"
          >
            去算薪
          </VbenButton>
        </div>
      </template>
      <a-empty v-else-if="!loading" description="未找到周期" />
    </a-spin>
  </Drawer>
</template>
