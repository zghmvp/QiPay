<script lang="ts" setup>
import type { RecalcJobDetail } from '../types/dashboard';

import { computed } from 'vue';
import { useRouter } from 'vue-router';

const props = withDefaults(
  defineProps<{
    job: RecalcJobDetail;
    testidPrefix?: string;
  }>(),
  {
    testidPrefix: 'recalc-job',
  },
);

const router = useRouter();

const failed = computed(() => {
  const job = props.job;
  return (
    job.status === 'failed' ||
    (job.failed_rider_count ?? job.payload?.failed_rider_count ?? 0) > 0
  );
});

const failedPeriodIds = computed(() => {
  const payload = props.job.payload;
  const ids = payload?.failed_period_ids ?? [];
  const extra = (payload?.failed ?? [])
    .map((row) => Number(row.period_id))
    .filter((n) => Number.isFinite(n) && n > 0);
  return [...new Set([...ids.map(Number), ...extra].filter((n) => n > 0))];
});

const calcPeriodIds = computed(() => {
  if (failedPeriodIds.value.length) return failedPeriodIds.value;
  const ids = (props.job.payload?.period_ids ?? [])
    .map(Number)
    .filter((n) => Number.isFinite(n) && n > 0);
  return [...new Set(ids)];
});

const failCount = computed(
  () => props.job.failed_rider_count ?? props.job.payload?.failed_rider_count ?? 0,
);

function goCalc(periodId: number) {
  void router.push({ path: `/rider-salary/period/${periodId}/calculate` });
}
</script>

<template>
  <div :data-testid="testidPrefix">
    <a-alert
      v-if="job.status === 'queued' || job.status === 'running'"
      show-icon
      type="info"
      :message="`最近重算：${job.status_label || job.status}`"
      :description="job.message || '完成后请核对算薪页，勿当作已出账'"
    />
    <a-alert
      v-else-if="failed"
      show-icon
      type="error"
      :data-testid="`${testidPrefix}-failed`"
      :message="
        job.message?.includes('部分失败')
          ? `最近重算部分失败${failCount ? `：失败 ${failCount} 人` : ''}`
          : `最近重算失败${failCount ? `：失败 ${failCount} 人` : ''}`
      "
      :description="job.message || '请到算薪页查看失败清单'"
    />
    <a-alert
      v-else
      show-icon
      type="info"
      :message="job.message || '最近重算已结束'"
      description="导入或批量重算完成 ≠ 已出账，请到周期算薪页核对。"
    />
    <div
      v-if="calcPeriodIds.length"
      class="mt-2 flex flex-wrap gap-2"
    >
      <a-button
        v-for="pid in calcPeriodIds"
        :key="pid"
        size="small"
        :data-testid="`${testidPrefix}-goto-calc`"
        @click="goCalc(pid)"
      >
        去算薪页 #{{ pid }}
      </a-button>
    </div>
  </div>
</template>
