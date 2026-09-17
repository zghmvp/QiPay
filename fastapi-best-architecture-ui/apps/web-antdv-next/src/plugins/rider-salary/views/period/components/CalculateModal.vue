<script lang="ts" setup>
/**
 * CalculateModal 已退役：列表「算薪」只进 /period/:id/calculate。
 * 残留引用若仍 open，立即跳转，不可在此完成算薪。
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
  <Modal title="正在跳转算薪页">
    <a-alert
      show-icon
      type="info"
      data-testid="period-calc-modal-retired"
      message="算薪已迁至独立页，不能在此弹窗完成计算。正在跳转…"
    />
  </Modal>
</template>
