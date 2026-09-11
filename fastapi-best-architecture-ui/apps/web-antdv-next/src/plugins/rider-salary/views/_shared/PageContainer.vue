<script lang="ts" setup>
import { Page } from '@vben/common-ui';
</script>

<template>
  <Page auto-content-height>
    <div class="rs-page-body flex h-full min-h-0 flex-col">
      <slot></slot>
    </div>
  </Page>
</template>

<style scoped>
/*
  Page auto-content-height 给内容区定高；useVbenVxeGrid 根节点是 h-full。
  中间层必须把高度传下去，否则 height:'auto' 会按内容收缩。
*/
.rs-page-body > :deep(.h-full.rounded-md) {
  flex: 1 1 0%;
  min-height: 0;
}
</style>
