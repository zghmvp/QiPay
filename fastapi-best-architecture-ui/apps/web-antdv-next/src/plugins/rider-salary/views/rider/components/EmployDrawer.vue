<script lang="ts" setup>
import type { RiderResult } from '../../../types/rider';

import { ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import EmployPanel from './EmployPanel.vue';

const rider = ref<RiderResult>();

const [Drawer, drawerApi] = useVbenDrawer({
  class: 'w-[560px]',
  destroyOnClose: true,
  footer: false,
  onOpenChange(isOpen) {
    if (!isOpen) return;
    rider.value = drawerApi.getData<RiderResult>();
  },
});
</script>

<template>
  <Drawer :title="`用工类型历史 · ${rider?.name || ''}`">
    <EmployPanel v-if="rider" :rider="rider" />
  </Drawer>
</template>
