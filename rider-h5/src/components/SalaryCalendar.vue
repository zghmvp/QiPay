<script setup lang="ts">
import { computed } from 'vue'
import type { CalendarDayItem, CalendarPlanBand } from '@/types'
import { buildMonthMatrix, formatMonthTitle, shiftMonth, WEEKDAY_LABELS } from '@/utils/date'
import { isNegativeMoney, isPositiveMoney, moneyNumber } from '@/utils/money'
import dayjs from 'dayjs'

const props = defineProps<{
  month: string
  days: CalendarDayItem[]
  planBands: CalendarPlanBand[]
}>()

const emit = defineEmits<{
  'update:month': [value: string]
  select: [date: string]
}>()

const matrix = computed(() => buildMonthMatrix(props.month))
const dayMap = computed(() => {
  const map = new Map<string, CalendarDayItem>()
  for (const day of props.days) map.set(day.date, day)
  return map
})

const today = dayjs().format('YYYY-MM-DD')

function bandFor(date: string): CalendarPlanBand | undefined {
  return props.planBands.find((band) => date >= band.start && date <= band.end)
}

function isBandStart(date: string, band: CalendarPlanBand | undefined): boolean {
  if (!band) return false
  if (date === band.start) return true
  const monthStart = `${props.month}-01`
  return date === monthStart && band.start < monthStart
}

function statusDot(status: string | undefined): 'gray' | 'red' | '' {
  if (status === 'not_imported') return 'gray'
  if (status === 'no_plan') return 'red'
  return ''
}

function prev() {
  emit('update:month', shiftMonth(props.month, -1))
}

function next() {
  emit('update:month', shiftMonth(props.month, 1))
}

function onCell(date: string, inMonth: boolean) {
  if (!inMonth) {
    emit('update:month', date.slice(0, 7))
    return
  }
  emit('select', date)
}
</script>

<template>
  <div class="cal">
    <div class="cal-nav">
      <button type="button" class="nav-btn" @click="prev">上一月</button>
      <strong>{{ formatMonthTitle(month) }}</strong>
      <button type="button" class="nav-btn" @click="next">下一月</button>
    </div>
    <div class="week-head">
      <span v-for="label in WEEKDAY_LABELS" :key="label">{{ label }}</span>
    </div>
    <div v-for="(week, wi) in matrix" :key="wi" class="week-row">
      <button
        v-for="cell in week"
        :key="cell.format('YYYY-MM-DD')"
        type="button"
        class="cell"
        :class="{
          muted: cell.format('YYYY-MM') !== month,
          today: cell.format('YYYY-MM-DD') === today,
          locked: dayMap.get(cell.format('YYYY-MM-DD'))?.is_locked,
        }"
        @click="onCell(cell.format('YYYY-MM-DD'), cell.format('YYYY-MM') === month)"
      >
        <span
          class="band"
          :style="{
            background: bandFor(cell.format('YYYY-MM-DD'))?.color || 'transparent',
          }"
        >
          <em
            v-if="
              cell.format('YYYY-MM') === month &&
              isBandStart(cell.format('YYYY-MM-DD'), bandFor(cell.format('YYYY-MM-DD')))
            "
          >
            {{ bandFor(cell.format('YYYY-MM-DD'))?.short_name }}
          </em>
        </span>
        <span class="date">{{ cell.date() }}</span>
        <span
          v-if="cell.format('YYYY-MM') === month && dayMap.get(cell.format('YYYY-MM-DD'))"
          class="count display-num"
        >
          {{ dayMap.get(cell.format('YYYY-MM-DD'))!.order_count }}
        </span>
        <span class="marks">
          <i
            v-if="
              isPositiveMoney(dayMap.get(cell.format('YYYY-MM-DD'))?.net_adjust) &&
              moneyNumber(dayMap.get(cell.format('YYYY-MM-DD'))?.net_adjust) >= 0.005
            "
            class="dot green"
          />
          <i
            v-if="isNegativeMoney(dayMap.get(cell.format('YYYY-MM-DD'))?.net_adjust)"
            class="dot red"
          />
          <i
            v-if="statusDot(dayMap.get(cell.format('YYYY-MM-DD'))?.day_status)"
            class="dot"
            :class="statusDot(dayMap.get(cell.format('YYYY-MM-DD'))?.day_status)"
          />
        </span>
      </button>
    </div>
    <div class="legend">
      <span><i class="dot gray" />未导入</span>
      <span><i class="dot red" />无方案 / 扣款</span>
      <span><i class="dot green" />奖励</span>
    </div>
  </div>
</template>

<style scoped>
.cal {
  background: var(--paper-2);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 10px 8px 8px;
}

.cal-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 6px 10px;
}

.nav-btn {
  border: 0;
  background: transparent;
  color: var(--vis-deep);
  font-size: 13px;
}

.week-head,
.week-row {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
}

.week-head span {
  text-align: center;
  font-size: 11px;
  color: var(--mute);
  padding-bottom: 6px;
}

.cell {
  position: relative;
  min-height: 62px;
  border: 0;
  background: transparent;
  padding: 10px 2px 6px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.cell.muted {
  opacity: 0.35;
}

.cell.today .date {
  background: var(--ink);
  color: #fff;
  border-radius: 50%;
  width: 20px;
  height: 20px;
  line-height: 20px;
}

.cell.locked .date::after {
  content: '锁';
  position: absolute;
  right: 2px;
  top: 10px;
  font-size: 9px;
  color: var(--mute);
}

.band {
  position: absolute;
  left: 3px;
  right: 3px;
  top: 2px;
  height: 4px;
  border-radius: 2px;
  overflow: visible;
}

.band em {
  position: absolute;
  left: 0;
  top: 5px;
  font-style: normal;
  font-size: 9px;
  color: var(--ink);
  white-space: nowrap;
  max-width: 42px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.date {
  font-size: 12px;
  margin-top: 6px;
}

.count {
  font-size: 13px;
  color: var(--ink-2);
}

.marks {
  min-height: 8px;
  display: flex;
  gap: 3px;
}
</style>
