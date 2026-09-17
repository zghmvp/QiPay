<script lang="ts" setup>
import type { AdvanceQuota, AdvanceResult } from '../../../types/advance';

import { ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { getAdvanceApi } from '../../../api/advance';
import MoneyText from '../../../components/MoneyText.vue';
import StatusTag from '../../../components/StatusTag.vue';
import {
  ADVANCE_STATUS_OPTIONS,
  DEDUCT_STATUS_OPTIONS,
} from '../../../constants/enums';
import { toDateTimeString } from '../../../utils/date';
import { formatAdvanceQuota, resolveAdvanceQuota } from '../helpers';

const loading = ref(false);
const detail = ref<AdvanceResult>();
const quota = ref<AdvanceQuota | null>(null);

const [Drawer, drawerApi] = useVbenDrawer({
  class: 'w-[560px]',
  cancelText: '关闭',
  destroyOnClose: true,
  showConfirmButton: false,
  async onOpenChange(isOpen) {
    if (!isOpen) return;
    const payload = drawerApi.getData<{ id?: number; row?: AdvanceResult }>();
    const pk = payload?.id;
    detail.value = undefined;
    quota.value = resolveAdvanceQuota(payload?.row);
    if (!pk) return;
    loading.value = true;
    try {
      detail.value = await getAdvanceApi(pk);
      quota.value = resolveAdvanceQuota(detail.value) ?? quota.value;
    } finally {
      loading.value = false;
    }
  },
});
</script>

<template>
  <Drawer title="预支详情">
    <a-spin :spinning="loading">
      <template v-if="detail">
        <div data-testid="advance-detail-open">
        <a-descriptions bordered size="small" :column="1" class="mb-4">
          <a-descriptions-item label="骑手">
            {{ [detail.rider_job_no, detail.rider_name].filter(Boolean).join(' ') || '—' }}
          </a-descriptions-item>
          <a-descriptions-item label="站点">{{ detail.site_name || '—' }}</a-descriptions-item>
          <a-descriptions-item v-if="quota" label="本月预支次数">
            {{ formatAdvanceQuota(quota) }}
          </a-descriptions-item>
          <a-descriptions-item label="金额">
            <MoneyText :value="detail.amount" />
          </a-descriptions-item>
          <a-descriptions-item label="原因">{{ detail.reason }}</a-descriptions-item>
          <a-descriptions-item label="状态">
            <StatusTag :options="ADVANCE_STATUS_OPTIONS" :value="detail.status" />
          </a-descriptions-item>
          <a-descriptions-item label="抵扣">
            <StatusTag :options="DEDUCT_STATUS_OPTIONS" :value="detail.deduct_status" />
          </a-descriptions-item>
          <a-descriptions-item label="已抵扣">
            <MoneyText :value="detail.deducted_amount" />
          </a-descriptions-item>
          <a-descriptions-item label="待抵扣">
            <MoneyText :value="detail.remaining_amount" />
          </a-descriptions-item>
          <a-descriptions-item label="审核备注">
            {{ detail.approve_remark || '—' }}
          </a-descriptions-item>
        </a-descriptions>
        <h4 class="mb-2 font-medium">操作时间线</h4>
        <a-timeline v-if="detail.timeline?.length">
          <a-timeline-item
            v-for="(item, index) in detail.timeline"
            :key="`${item.operate_time}-${index}`"
            :color="index === (detail.timeline?.length ?? 1) - 1 ? 'blue' : 'gray'"
          >
            <div class="font-medium">{{ item.action }} · {{ item.operator_name }}</div>
            <div class="text-muted-foreground text-xs">
              {{ toDateTimeString(item.operate_time) }}
            </div>
            <div v-if="item.description" class="mt-1 text-sm">{{ item.description }}</div>
            <div v-if="item.reason" class="text-muted-foreground text-sm">
              原因：{{ item.reason }}
            </div>
          </a-timeline-item>
        </a-timeline>
        <a-empty v-else description="暂无时间线" />
        </div>
      </template>
      <a-empty v-else-if="!loading" description="未找到预支单" />
    </a-spin>
  </Drawer>
</template>
