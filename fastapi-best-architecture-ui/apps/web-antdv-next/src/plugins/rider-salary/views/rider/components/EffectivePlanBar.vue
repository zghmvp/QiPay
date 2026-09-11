<script lang="ts" setup>
import type { EffectivePlanSegment } from '../../../types/rider';

import { computed } from 'vue';

const props = withDefaults(
  defineProps<{
    loading?: boolean;
    segments: EffectivePlanSegment[];
    title?: string;
  }>(),
  { loading: false, title: '生效方案区间' },
);

const rows = computed(() =>
  props.segments.map((item) => ({
    ...item,
    label: item.plan_short_name || (item.plan_version_id ? `版本 ${item.plan_version_id}` : '未绑定'),
  })),
);
</script>

<template>
  <div class="rounded border p-3">
    <div class="mb-2 text-sm font-medium">{{ title }}</div>
    <a-spin :spinning="loading">
      <a-empty v-if="rows.length === 0" description="该时段内无生效方案" />
      <div v-else class="flex flex-col gap-2">
        <div
          v-for="(item, index) in rows"
          :key="`${item.start}-${item.end}-${index}`"
          class="flex items-center gap-3 rounded bg-muted/30 px-3 py-2"
        >
          <span
            class="inline-block size-3 shrink-0 rounded-full"
            :style="{ background: item.plan_color || (item.plan_version_id ? '#1677ff' : '#d9d9d9') }"
          ></span>
          <div class="min-w-0 flex-1">
            <div class="font-medium">{{ item.label }}</div>
            <div class="text-muted-foreground text-xs">
              {{ item.start }} ~ {{ item.end }}
            </div>
          </div>
        </div>
      </div>
    </a-spin>
  </div>
</template>
