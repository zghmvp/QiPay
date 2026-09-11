<script setup lang="ts">
import { ConfigProvider } from 'vant'
import zhCN from 'vant/es/locale/lang/zh-CN'

const themeVars = {
  primaryColor: '#ff7a1a',
  successColor: '#1f8a70',
  dangerColor: '#c44536',
  warningColor: '#c45c26',
}
</script>

<template>
  <ConfigProvider :locale="zhCN" :theme-vars="themeVars">
    <div class="phone-shell">
      <router-view />
    </div>
  </ConfigProvider>
</template>
