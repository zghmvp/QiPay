<script lang="ts" setup>
import { onMounted, ref } from 'vue';

import { getSiteManagersApi } from '../../../api/site';
import {
  getCachedManagerCount,
  setCachedManagerCount,
} from '../manager-count-cache';

const props = defineProps<{ siteId: number }>();

const count = ref<null | number>(getCachedManagerCount(props.siteId));

onMounted(async () => {
  if (count.value !== null) return;
  try {
    const managers = await getSiteManagersApi(props.siteId);
    const next = managers?.length ?? 0;
    setCachedManagerCount(props.siteId, next);
    count.value = next;
  } catch {
    count.value = 0;
  }
});
</script>

<template>
  <span>{{ count === null ? '…' : count }}</span>
</template>
