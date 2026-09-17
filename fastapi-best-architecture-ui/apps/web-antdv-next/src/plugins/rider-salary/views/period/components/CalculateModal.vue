<script lang="ts" setup>
/**
 * CalculateModal 已退役：主路径为 /period/:id/calculate。
 * 残留引用若仍 open，则跳转到独立算薪页。
 */
import type { PeriodResult } from '../../../types/period';

import { useRouter } from 'vue-router';

import { useVbenModal } from '@vben/common-ui';

const router = useRouter();

const [Modal, modalApi] = useVbenModal({
  class: 'w-[360px]',
  showConfirmButton: false,
  cancelText: '关闭',
  destroyOnClose: true,
  async onOpenChange(isOpen) {
    if (!isOpen) return;
    const period = modalApi.getData<PeriodResult>();
    if (period?.id) {
      await modalApi.close();
      await router.replace({
        path: `/rider-salary/period/${period.id}/calculate`,
      });
    }
  },
});
</script>

<template>
  <Modal title="计算周期薪资">
    <a-alert
      show-icon
      type="info"
      message="算薪已迁至独立页，正在跳转…"
    />
  </Modal>
</template>
