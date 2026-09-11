<script lang="ts" setup>
defineProps<{
  hint?: string;
  title?: string;
}>();
</script>

<template>
  <a-empty :description="title || '功能开发中'">
    <p class="text-muted-foreground mt-2 text-sm">
      {{ hint || '该页面由后续模块实现，菜单已预留。' }}
    </p>
  </a-empty>
</template>
