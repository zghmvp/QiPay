<script lang="ts" setup>
/**
 * 已退役：嵌套薪资明细抽屉。保留薄包装，打开时跳转独立页。
 */
import { useRouter } from 'vue-router';

import { useVbenDrawer } from '@vben/common-ui';

const router = useRouter();

const [Drawer, drawerApi] = useVbenDrawer({
  class: 'w-[420px]',
  cancelText: '关闭',
  destroyOnClose: true,
  showConfirmButton: false,
  onOpenChange(isOpen) {
    if (!isOpen) return;
    const data = drawerApi.getData<{ id?: number }>();
    if (data?.id) {
      drawerApi.close();
      router.push({ path: `/rider-salary/payroll/${data.id}` });
    }
  },
});
</script>

<template>
  <Drawer title="薪资明细">
    <a-empty description="已改为独立页面，正在跳转…" />
  </Drawer>
</template>
