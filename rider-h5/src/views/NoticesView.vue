<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Empty, NavBar, Popup } from 'vant'
import AppTabbar from '@/components/AppTabbar.vue'
import { getNotices } from '@/api/me'
import { toDateTimeString } from '@/utils/date'
import type { NoticeDetail } from '@/types'

const loading = ref(true)
const list = ref<NoticeDetail[]>([])
const current = ref<NoticeDetail | null>(null)
const show = computed({
  get: () => current.value !== null,
  set: (value: boolean) => {
    if (!value) current.value = null
  },
})

onMounted(async () => {
  try {
    list.value = await getNotices()
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div>
    <NavBar title="公告" />
    <div class="page-body">
      <Empty v-if="!loading && !list.length" description="暂无公告" />
      <button
        v-for="item in list"
        :key="item.id"
        type="button"
        class="card-block notice"
        @click="current = item"
      >
        <h3>{{ item.title }}</h3>
        <p class="muted">{{ toDateTimeString(item.publish_time || item.created_time) }}</p>
      </button>
    </div>
    <Popup v-model:show="show" position="bottom" round :style="{ minHeight: '40%' }">
      <div v-if="current" class="detail">
        <h2>{{ current.title }}</h2>
        <p class="muted">{{ toDateTimeString(current.publish_time || current.created_time) }}</p>
        <div class="content">{{ current.content }}</div>
      </div>
    </Popup>
    <AppTabbar />
  </div>
</template>

<style scoped>
.notice {
  display: block;
  width: 100%;
  text-align: left;
  padding: 14px;
  margin-bottom: 10px;
  border: 1px solid var(--line);
  background: var(--paper-2);
}

.notice h3 {
  margin: 0 0 6px;
  font-size: 15px;
}

.detail {
  padding: 20px 16px 32px;
}

.detail h2 {
  margin: 0 0 8px;
  font-size: 18px;
}

.content {
  white-space: pre-wrap;
  line-height: 1.7;
  margin-top: 12px;
}
</style>
