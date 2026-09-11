<script lang="ts" setup>
import type { RiderResult } from '../../../types/rider';

import { ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import BindingPanel from './BindingPanel.vue';

const rider = ref<RiderResult>();

const [Drawer, drawerApi] = useVbenDrawer({
  class: 'w-[640px]',
  destroyOnClose: true,
  footer: false,
  onOpenChange(isOpen) {
    if (!isOpen) return;
    rider.value = drawerApi.getData<RiderResult>();
  },
});
</script>

<template>
  <Drawer :title="`方案绑定 · ${rider?.name || ''}`">
    <BindingPanel v-if="rider" :rider="rider" />
  </Drawer>
</template>
