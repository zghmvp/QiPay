<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Cell, Empty, NavBar } from 'vant'
import AppTabbar from '@/components/AppTabbar.vue'
import MoneyText from '@/components/MoneyText.vue'
import { getAdjustments } from '@/api/me'
import { currentMonth, formatMonthTitle, shiftMonth } from '@/utils/date'
import type { MeAdjustmentItem } from '@/types'

const month = ref(currentMonth())
const loading = ref(true)
const items = ref<MeAdjustmentItem[]>([])

const groups = computed(() => {
  const map = new Map<string, MeAdjustmentItem[]>()
  for (const item of items.value) {
    const key = item.biz_date
    const list = map.get(key) || []
    list.push(item)
    map.set(key, list)
  }
  return [...map.entries()].sort((a, b) => (a[0] < b[0] ? 1 : -1))
})

async function load() {
  loading.value = true
  try {
    items.value = await getAdjustments(month.value)
  } finally {
    loading.value = false
  }
}

function changeMonth(delta: number) {
  month.value = shiftMonth(month.value, delta)
  void load()
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div>
    <NavBar title="奖惩明细" />
    <div class="page-body">
      <div class="month-bar">
        <button type="button" @click="changeMonth(-1)">上一月</button>
        <strong>{{ formatMonthTitle(month) }}</strong>
        <button type="button" @click="changeMonth(1)">下一月</button>
      </div>
      <Empty v-if="!loading && !items.length" description="本月暂无奖惩" />
      <section v-for="[date, rows] in groups" :key="date" class="card-block group">
        <h3>{{ date }}</h3>
        <Cell
          v-for="row in rows"
          :key="row.id"
          :title="row.subject_name"
          :label="row.remark || '无备注'"
        >
          <template #value>
            <MoneyText :value="row.amount" signed />
          </template>
        </Cell>
      </section>
    </div>
    <AppTabbar />
  </div>
</template>

<style scoped>
.month-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.month-bar button {
  border: 0;
  background: transparent;
  color: var(--vis-deep);
}

.group {
  margin-bottom: 12px;
}

.group h3 {
  margin: 0;
  padding: 10px 14px 0;
  font-size: 13px;
  color: var(--mute);
}
</style>
