<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Empty, Skeleton, Tag } from 'vant'
import AppTabbar from '@/components/AppTabbar.vue'
import MoneyText from '@/components/MoneyText.vue'
import SalaryCalendar from '@/components/SalaryCalendar.vue'
import { getCalendar, getPayrollEstimate, getProfile } from '@/api/me'
import {
  enumLabel,
  PERIOD_STATUS_OPTIONS,
  PLAN_MODE_TAG_OPTIONS,
  vantTagType,
  enumColor,
} from '@/constants/enums'
import { useAuthStore } from '@/stores/auth'
import { currentMonth } from '@/utils/date'
import type { CalendarMonth, PayrollEstimate } from '@/types'

const router = useRouter()
const auth = useAuthStore()
const month = ref(currentMonth())
const loading = ref(true)
const estimate = ref<PayrollEstimate | null>(null)
const calendar = ref<CalendarMonth | null>(null)

const greeting = computed(() => {
  const name = auth.profile?.name || '骑手'
  const site = auth.profile?.site_name || '未分配站点'
  return `${name} · ${site}`
})

const plan = computed(() => auth.profile?.current_plan)
const emptyMonth = computed(() => (calendar.value?.summary.order_count ?? 0) === 0)

const locked = computed(() => {
  const status = estimate.value?.period_status
  return status === 'locked' || status === 'paid'
})

async function load() {
  loading.value = true
  try {
    const [profile, est, cal] = await Promise.all([
      getProfile(),
      getPayrollEstimate(),
      getCalendar(month.value),
    ])
    auth.profile = profile
    estimate.value = est
    calendar.value = cal
  } finally {
    loading.value = false
  }
}

async function onMonth(value: string) {
  month.value = value
  calendar.value = await getCalendar(value)
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div>
    <header class="top">
      <div>
        <p class="waybill-kicker">本期薪资</p>
        <h1>{{ greeting }}</h1>
      </div>
      <Tag
        v-if="plan?.short_name"
        round
        :type="vantTagType(enumColor(PLAN_MODE_TAG_OPTIONS, plan.mode_tag))"
        @click="router.push('/plan')"
      >
        {{ plan.short_name }}
      </Tag>
    </header>

    <div class="page-body">
      <Skeleton :loading="loading" :row="4" title>
        <section v-if="estimate" class="waybill">
          <span v-if="estimate.is_estimate" class="stamp">预估</span>
          <p class="waybill-kicker">本期预计工资</p>
          <p class="waybill-amount display-num">
            <MoneyText :value="estimate.net_estimate" />
          </p>
          <p class="muted">
            {{ estimate.period_range }}
            ·
            {{ enumLabel(PERIOD_STATUS_OPTIONS, estimate.period_status) }}
            <template v-if="estimate.is_estimate && !locked"> · 未锁账，仅供参考</template>
            <template v-else-if="locked"> · 已锁定</template>
          </p>
          <div class="metric-grid">
            <div>
              <span class="label">单量</span>
              <span class="value display-num">{{ estimate.order_count }}</span>
            </div>
            <div>
              <span class="label">应发</span>
              <span class="value"><MoneyText :value="estimate.gross" /></span>
            </div>
            <div>
              <span class="label">代扣</span>
              <span class="value"><MoneyText :value="estimate.deduction_total" /></span>
            </div>
            <div>
              <span class="label">预支抵扣</span>
              <span class="value"><MoneyText :value="estimate.advance_deduction_estimate" /></span>
            </div>
          </div>
        </section>
      </Skeleton>

      <div class="section-title">
        <span>月历</span>
        <span class="muted" @click="router.push('/plan')">查看方案</span>
      </div>
      <div v-if="calendar?.plan_bands?.length" class="chip-row">
        <Tag
          v-for="band in calendar.plan_bands"
          :key="`${band.plan_version_id}-${band.start}`"
          round
          :color="band.color || '#ff7a1a'"
          text-color="#fff"
        >
          {{ band.short_name || '方案' }} {{ band.start.slice(5) }}~{{ band.end.slice(5) }}
        </Tag>
      </div>
      <SalaryCalendar
        v-if="calendar"
        :month="month"
        :days="calendar.days"
        :plan-bands="calendar.plan_bands"
        @update:month="onMonth"
        @select="(date) => router.push(`/day/${date}`)"
      />
      <Empty v-if="!loading && emptyMonth" description="本月暂无订单" />
    </div>
    <AppTabbar />
  </div>
</template>

<style scoped>
.top {
  background: #15202b;
  color: #f4efe6;
  padding: 18px 16px 16px;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.top h1 {
  margin: 6px 0 0;
  font-size: 20px;
}
</style>
