<script lang="ts" setup>
import type { BandSlice } from '../bands';

defineProps<{
  slices: BandSlice[];
}>();
</script>

<template>
  <div class="pointer-events-none absolute inset-x-0 top-0 z-10 h-[18px]">
    <a-tooltip
      v-for="slice in slices"
      :key="slice.key"
      :title="slice.tooltip"
    >
      <div
        class="pointer-events-auto absolute top-0 h-[18px] overflow-hidden rounded text-[11px] leading-[18px] text-white"
        :style="{
          background: slice.color,
          left: `calc(${(slice.colStart / 7) * 100}% + 2px)`,
          width: `calc(${((slice.colEnd - slice.colStart + 1) / 7) * 100}% - 4px)`,
        }"
      >
        <span class="px-1">{{ slice.label }}</span>
      </div>
    </a-tooltip>
  </div>
</template>
