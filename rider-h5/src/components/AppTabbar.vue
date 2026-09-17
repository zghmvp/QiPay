<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { Tabbar, TabbarItem } from 'vant'

const route = useRoute()
const router = useRouter()
const active = String(route.meta.tab || '')

function go(path: string) {
  if (route.path !== path) void router.replace(path)
}
</script>

<template>
  <Tabbar
    :model-value="active"
    :border="false"
    placeholder
    safe-area-inset-bottom
    active-color="#ff7a1a"
    inactive-color="#6b7380"
  >
    <TabbarItem name="home" icon="home-o" @click="go('/home')">首页</TabbarItem>
    <TabbarItem name="adjustments" icon="records" @click="go('/adjustments')">奖惩</TabbarItem>
    <TabbarItem name="advance" icon="gold-coin-o" @click="go('/advance')">预支</TabbarItem>
    <TabbarItem name="me" icon="user-o" @click="go('/me')">我的</TabbarItem>
  </Tabbar>
</template>
