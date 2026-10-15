<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Tabbar, TabbarItem } from 'vant'
import { useMenuStore } from '@/stores/menu'
import { getToken } from '@/utils/storage'

const route = useRoute()
const router = useRouter()
const menus = useMenuStore()
const active = String(route.meta.tab || '')

onMounted(() => {
  if (getToken() && !menus.loaded) void menus.load().catch(() => undefined)
})

const items = computed(() =>
  [
    { name: 'home', icon: 'home-o', path: '/home', label: '首页', show: menus.flags.show_home },
    { name: 'adjustments', icon: 'records', path: '/adjustments', label: '奖惩', show: menus.flags.show_adjustments },
    { name: 'advance', icon: 'gold-coin-o', path: '/advance', label: '预支', show: menus.flags.show_advance },
    { name: 'notices', icon: 'volume-o', path: '/notices', label: '公告', show: menus.flags.show_notices },
    { name: 'me', icon: 'user-o', path: '/me', label: '我的', show: true },
  ].filter((item) => item.show),
)

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
    <TabbarItem v-for="item in items" :key="item.name" :name="item.name" :icon="item.icon" @click="go(item.path)">
      {{ item.label }}
    </TabbarItem>
  </Tabbar>
</template>
