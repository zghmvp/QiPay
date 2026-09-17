<script lang="ts" setup>
import type {
  CalculatePeriodResult,
  PeriodResult,
} from '../../../types/period';
import type { RiderResult } from '../../../types/rider';

import { ref } from 'vue';

import { useVbenModal } from '@vben/common-ui';

import { message } from 'antdv-next';

import { calculatePeriodApi } from '../../../api/period';
import { getRiderListApi } from '../../../api/rider';

const riderIds = ref<number[]>([]);
const options = ref<{ label: string; value: number }[]>([]);
const loading = ref(false);
const personal = ref(false);
const lastResult = ref<CalculatePeriodResult | null>(null);

function formatFailures(res: CalculatePeriodResult): string {
  return (res.failed ?? [])
    .map((row) => {
      const who = row.job_no ? `工号 ${row.job_no}` : `骑手 #${row.rider_id}`;
      return `${who}：${(row.errors ?? []).join('；')}`;
    })
    .join('\n');
}

const [Modal, modalApi] = useVbenModal({
  class: 'w-[560px]',
  confirmText: '开始算薪',
  destroyOnClose: true,
  async onConfirm() {
    const period = modalApi.getData<PeriodResult & { onSuccess?: () => void }>();
    if (!period?.id) return;
    modalApi.lock();
    lastResult.value = null;
    try {
      const res = await calculatePeriodApi(period.id, {
        rider_ids: riderIds.value.length ? riderIds.value : null,
      });
      lastResult.value = res;
      const failedCount = res.failed?.length ?? 0;
      if (res.queued) {
        message.info('算薪已转入后台处理');
      } else if (failedCount > 0) {
        message.error(
          `算薪部分失败：成功 ${res.calculated} 人，失败 ${failedCount} 人，请查看错误列表`,
        );
      } else {
        message.success(`已计算 ${res.calculated} 名骑手`);
      }
      // 非阻断提示仅保留「转入后台」类；禁止把硬失败当 warning toast
      const tips = (res.warnings ?? []).filter((w) => w.includes('后台'));
      if (tips.length) {
        message.info(tips.join('；'));
      }
      if (failedCount === 0) {
        period.onSuccess?.();
        await modalApi.close();
      } else {
        period.onSuccess?.();
      }
    } finally {
      modalApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) return;
    riderIds.value = [];
    options.value = [];
    personal.value = false;
    lastResult.value = null;
    const period = modalApi.getData<PeriodResult>();
    if (!period?.site_id) return;
    if (period.rider_id) {
      personal.value = true;
      riderIds.value = [period.rider_id];
    }
    loading.value = true;
    try {
      const res = await getRiderListApi({
        page: 1,
        site_id: period.site_id,
        size: 200,
      });
      options.value = (res?.items ?? []).map((item: RiderResult) => ({
        label: `${item.job_no} ${item.name}`,
        value: item.id,
      }));
    } finally {
      loading.value = false;
    }
  },
});
</script>

<template>
  <Modal title="计算周期薪资">
    <a-alert
      class="mb-3"
      show-icon
      type="info"
      message="不选骑手则计算周期内全部骑手。个性化周期骑手不会写入站点级结果。"
    />
    <a-select
      v-model:value="riderIds"
      allow-clear
      class="w-full"
      mode="multiple"
      placeholder="默认全部骑手"
      :disabled="personal"
      :loading="loading"
      :options="options"
      option-filter-prop="label"
      show-search
    />
    <a-alert
      v-if="lastResult?.failed?.length"
      class="mt-3"
      show-icon
      type="error"
      message="算薪失败清单"
      :description="formatFailures(lastResult)"
    />
  </Modal>
</template>
