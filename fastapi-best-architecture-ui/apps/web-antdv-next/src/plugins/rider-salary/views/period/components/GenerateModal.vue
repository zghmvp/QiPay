<script lang="ts" setup>
import { ref } from 'vue';

import { useVbenModal } from '@vben/common-ui';

import { message } from 'antdv-next';

import { generatePeriodsApi } from '../../../api/period';
import SiteSelect from '../../../components/SiteSelect.vue';
import { currentMonth } from '../../../utils/date';

const siteId = ref<number>();
const month = ref(currentMonth());

const [Modal, modalApi] = useVbenModal({
  class: 'w-[420px]',
  confirmText: '生成周期',
  destroyOnClose: true,
  async onConfirm() {
    if (!siteId.value) {
      message.warning('请选择站点');
      return;
    }
    if (!month.value) {
      message.warning('请选择月份');
      return;
    }
    modalApi.lock();
    try {
      const res = await generatePeriodsApi({
        month: month.value,
        site_id: siteId.value,
      });
      message.success(
        `新生成 ${res.created_count} 个周期，跳过已存在 ${res.skipped_count} 个`,
      );
      modalApi.getData<{ onSuccess?: () => void }>()?.onSuccess?.();
      await modalApi.close();
    } finally {
      modalApi.unlock();
    }
  },
  onOpenChange(isOpen) {
    if (!isOpen) return;
    siteId.value = undefined;
    month.value = currentMonth();
  },
});
</script>

<template>
  <Modal title="生成结算周期">
    <div class="flex flex-col gap-3">
      <div>
        <div class="mb-1 text-sm">站点</div>
        <SiteSelect v-model:value="siteId" />
      </div>
      <div>
        <div class="mb-1 text-sm">月份</div>
        <a-date-picker
          v-model:value="month"
          picker="month"
          format="YYYY-MM"
          value-format="YYYY-MM"
          class="w-full"
        />
      </div>
    </div>
  </Modal>
</template>
