<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NavBar } from 'vant'
import dayjs from 'dayjs'
import MoneyText from '@/components/MoneyText.vue'
import { getDayDetail } from '@/api/me'
import { useMenuStore } from '@/stores/menu'
import {
  DAY_STATUS_OPTIONS,
  enumColor,
  enumLabel,
  ORDER_STATUS_OPTIONS,
} from '@/constants/enums'

const PAGE_SIZE = 10
const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']

const menus = useMenuStore()
const route = useRoute()
const router = useRouter()
const date = computed(() => String(route.params.date || ''))
const loading = ref(true)
const detail = ref<Awaited<ReturnType<typeof getDayDetail>> | null>(null)
const orderPage = ref(1)
const adjustmentPage = ref(1)

const showAmount = computed(() => menus.flags.show_day_amount)
const parsedDate = computed(() => {
  const value = dayjs(date.value)
  return value.isValid() ? value : null
})
const dayTitle = computed(() => parsedDate.value?.format('M月D日') || date.value)
const heroMeta = computed(() => {
  const parts: string[] = []
  if (parsedDate.value) parts.push(`周${WEEKDAYS[parsedDate.value.day()]}`)
  const status = enumLabel(DAY_STATUS_OPTIONS, detail.value?.day_status)
  if (status) parts.push(status)
  const plan = detail.value?.plan?.short_name || detail.value?.plan?.plan_name
  if (plan) parts.push(plan)
  return parts.join(' · ')
})

function slicePage<T>(rows: T[], page: number) {
  const start = (page - 1) * PAGE_SIZE
  return rows.slice(start, start + PAGE_SIZE)
}

function pageCount(total: number) {
  return Math.max(1, Math.ceil(total / PAGE_SIZE))
}

function orderStamp(order: { deliver_time: string | null; order_time: string }) {
  return order.deliver_time || order.order_time || ''
}

const sortedOrders = computed(() =>
  [...(detail.value?.orders ?? [])].sort((a, b) => orderStamp(a).localeCompare(orderStamp(b))),
)
const orderRows = computed(() => slicePage(sortedOrders.value, orderPage.value))
const adjustmentRows = computed(() => slicePage(detail.value?.adjustments ?? [], adjustmentPage.value))
const orderPages = computed(() => pageCount(sortedOrders.value.length))
const adjustmentPages = computed(() => pageCount(detail.value?.adjustments.length ?? 0))
const allCompleted = computed(
  () => sortedOrders.value.length > 0 && sortedOrders.value.every((order) => order.status === 'completed'),
)
const unfinishedCount = computed(
  () => sortedOrders.value.filter((order) => order.status !== 'completed').length,
)
const timeSpan = computed(() => {
  const rows = sortedOrders.value
  if (!rows.length) return ''
  const first = clock(orderStamp(rows[0]))
  const last = clock(orderStamp(rows[rows.length - 1]))
  return first === last ? first : `${first}–${last}`
})

function pageRange(page: number, total: number) {
  const start = (page - 1) * PAGE_SIZE + 1
  const end = Math.min(page * PAGE_SIZE, total)
  return `${start}–${end} / ${total}`
}

function clock(value: string | null | undefined) {
  if (!value) return '—'
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('HH:mm') : '—'
}

function statusClass(status: string) {
  return enumColor(ORDER_STATUS_OPTIONS, status) === 'success' ? 'ok' : 'wait'
}

async function load() {
  loading.value = true
  orderPage.value = 1
  adjustmentPage.value = 1
  try {
    detail.value = await getDayDetail(date.value)
  } finally {
    loading.value = false
  }
}

watch(date, () => {
  void load()
}, { immediate: true })
</script>

<template>
  <div>
    <NavBar class="day-nav" :title="dayTitle" left-arrow :border="false" @click-left="router.back()" />
    <div v-if="detail" class="page-body no-tab">
      <section class="hero">
        <p class="waybill-kicker">{{ heroMeta }}</p>
        <div class="hero-main">
          <p class="count display-num">{{ detail.totals.order_count }}</p>
          <p class="unit">单</p>
          <div v-if="showAmount" class="net">
            <span>净额</span>
            <MoneyText :value="detail.totals.net" signed />
          </div>
          <div v-else-if="timeSpan" class="span">
            <span>配送时段</span>
            <strong>{{ timeSpan }}</strong>
          </div>
        </div>
        <p v-if="showAmount && timeSpan" class="fine">{{ timeSpan }} · 以站点公布为准</p>
        <p v-else-if="showAmount" class="fine">以站点公布为准</p>
      </section>

      <section class="sheet">
        <header>
          <span>订单</span>
          <em v-if="allCompleted">全部完成</em>
          <em v-else-if="unfinishedCount" class="warn">{{ unfinishedCount }} 单未完成</em>
        </header>
        <p v-if="!detail.orders.length" class="blank">当日没有订单</p>
        <template v-else>
          <div
            v-for="order in orderRows"
            :key="order.id"
            class="line"
            :class="{ amount: showAmount, marked: !allCompleted }"
          >
            <span class="time" :class="statusClass(order.status)">{{ clock(order.deliver_time || order.order_time) }}</span>
            <span class="no mono" :title="order.order_no">{{ order.order_no }}</span>
            <span v-if="!allCompleted && order.status !== 'completed'" class="pill wait">未完成</span>
            <span v-else-if="!allCompleted" class="mark" aria-label="配送完成" />
            <span v-if="showAmount" class="amt">
              <MoneyText :value="order.amount" />
            </span>
          </div>
          <div v-if="orderPages > 1" class="pager">
            <button type="button" :disabled="orderPage <= 1" @click="orderPage -= 1">上一页</button>
            <span>{{ pageRange(orderPage, detail.orders.length) }}</span>
            <button type="button" :disabled="orderPage >= orderPages" @click="orderPage += 1">下一页</button>
          </div>
        </template>
      </section>

      <section v-if="detail.adjustments.length" class="sheet">
        <header>
          <span>奖惩</span>
          <span>{{ detail.adjustments.length }}</span>
        </header>
        <template>
          <div
            v-for="item in adjustmentRows"
            :key="item.id"
            class="line adjust"
            :class="{ amount: showAmount }"
          >
            <span class="subject" :title="item.subject">{{ item.subject }}</span>
            <span class="remark" :title="item.remark || ''">{{ item.remark || '无备注' }}</span>
            <span v-if="showAmount" class="amt">
              <MoneyText :value="item.amount" signed />
            </span>
          </div>
          <div v-if="adjustmentPages > 1" class="pager">
            <button type="button" :disabled="adjustmentPage <= 1" @click="adjustmentPage -= 1">上一页</button>
            <span>{{ pageRange(adjustmentPage, detail.adjustments.length) }}</span>
            <button type="button" :disabled="adjustmentPage >= adjustmentPages" @click="adjustmentPage += 1">下一页</button>
          </div>
        </template>
      </section>
    </div>
    <p v-else-if="loading" class="wait-load">正在加载</p>
    <p v-else class="wait-load">当天明细加载失败</p>
  </div>
</template>

<style scoped>
.day-nav {
  --van-nav-bar-background: #15202b;
  --van-nav-bar-title-text-color: #f4efe6;
  --van-nav-bar-icon-color: #f4efe6;
  background: #15202b;
}

.hero {
  margin: -12px -14px 14px;
  padding: 6px 18px 16px;
  background: #15202b;
  color: #f4efe6;
}

.hero .waybill-kicker {
  color: rgb(244 239 230 / 62%);
}

.hero-main {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  margin-top: 8px;
}

.count {
  margin: 0;
  font-size: 52px;
  line-height: 0.85;
}

.unit {
  margin: 0 0 4px;
  font-size: 14px;
  color: rgb(244 239 230 / 72%);
}

.net {
  margin-left: auto;
  margin-bottom: 4px;
  text-align: right;
}

.net span {
  display: block;
  font-size: 11px;
  letter-spacing: 0.12em;
  color: rgb(244 239 230 / 62%);
}

.net :deep(.display-num) {
  font-size: 28px;
  line-height: 1;
}

.span {
  margin-left: auto;
  margin-bottom: 6px;
  text-align: right;
}

.span span {
  display: block;
  font-size: 11px;
  letter-spacing: 0.12em;
  color: rgb(244 239 230 / 62%);
}

.span strong {
  font-size: 18px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
}

.fine {
  margin: 10px 0 0;
  font-size: 11px;
  color: rgb(244 239 230 / 45%);
}

.sheet {
  margin-bottom: 12px;
  background: var(--paper-2);
  border: 1px solid var(--line);
  border-radius: 14px;
  overflow: hidden;
}

.sheet header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 12px 14px 8px;
  font-size: 15px;
  font-weight: 700;
}

.sheet header span:last-child {
  color: var(--mute);
  font-family: 'Barlow Condensed', 'DIN Alternate', sans-serif;
  font-size: 18px;
  font-weight: 700;
}

.sheet header em {
  font-style: normal;
  font-size: 12px;
  font-weight: 500;
  color: var(--earn);
}

.sheet header em.warn {
  color: var(--warn);
}

.line {
  display: grid;
  grid-template-columns: 46px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  min-height: 36px;
  padding: 0 12px;
  border-top: 1px solid var(--line);
}

.line.marked,
.line.amount {
  grid-template-columns: 46px minmax(0, 1fr) auto;
}

.line.marked.amount {
  grid-template-columns: 46px minmax(0, 1fr) auto auto;
}

.line.adjust {
  grid-template-columns: 88px minmax(0, 1fr);
}

.line.adjust.amount {
  grid-template-columns: 88px minmax(0, 1fr) auto;
}

.time,
.remark {
  color: var(--mute);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.time.ok {
  color: var(--ink-2);
}

.time.wait {
  color: var(--warn);
}

.mark {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--earn);
  justify-self: end;
}

.no,
.subject,
.remark {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.no {
  font-size: 13px;
  letter-spacing: -0.02em;
}

.subject {
  font-size: 13px;
}

.pill {
  justify-self: end;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 11px;
  line-height: 18px;
  white-space: nowrap;
}

.pill.ok {
  background: #e7f4ef;
  color: var(--earn);
}

.pill.wait {
  background: #f3efe8;
  color: var(--mute);
}

.amt {
  justify-self: end;
  font-size: 13px;
}

.blank {
  margin: 0;
  padding: 18px 14px 20px;
  border-top: 1px solid var(--line);
  color: var(--mute);
  font-size: 13px;
  text-align: center;
}

.pager {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  border-top: 1px solid var(--line);
  padding: 4px 6px;
}

.pager span {
  color: var(--ink-2);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.pager button {
  border: 0;
  background: transparent;
  color: var(--vis-deep);
  font: inherit;
  font-size: 13px;
  line-height: 32px;
  padding: 0 8px;
}

.pager button:first-child {
  justify-self: start;
}

.pager button:last-child {
  justify-self: end;
}

.pager button:disabled {
  color: #c9c0b4;
}

.wait-load {
  margin: 48px 0;
  color: var(--mute);
  text-align: center;
}
</style>
