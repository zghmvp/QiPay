<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Cell, CellGroup, Collapse, CollapseItem, Empty, NavBar, Tag } from 'vant'
import MoneyText from '@/components/MoneyText.vue'
import { getDayDetail } from '@/api/me'
import {
  DAY_STATUS_OPTIONS,
  enumLabel,
  ORDER_STATUS_OPTIONS,
  PERIOD_STATUS_OPTIONS,
  PLAN_MODE_TAG_OPTIONS,
  vantTagType,
  enumColor,
} from '@/constants/enums'
import { toDateTimeString } from '@/utils/date'
import type { CalendarDayDetail } from '@/types'

const route = useRoute()
const router = useRouter()
const date = computed(() => String(route.params.date || ''))
const loading = ref(true)
const detail = ref<CalendarDayDetail | null>(null)
const active = ref(['orders'])

onMounted(async () => {
  try {
    detail.value = await getDayDetail(date.value)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div>
    <NavBar :title="`${date} 明细`" left-arrow @click-left="router.back()" />
    <div v-if="detail" class="page-body no-tab">
      <section class="card-block info">
        <p>
          方案
          <strong>
            {{ detail.plan?.plan_name || '当日无生效方案' }}
          </strong>
          <Tag
            v-if="detail.plan?.short_name"
            size="small"
            round
            :type="vantTagType(enumColor(PLAN_MODE_TAG_OPTIONS, detail.plan.mode_tag))"
          >
            {{ detail.plan.short_name }}
          </Tag>
        </p>
        <p class="muted">
          周期 {{ detail.period?.range || '—' }}
          ·
          {{ enumLabel(PERIOD_STATUS_OPTIONS, detail.period?.status) }}
          ·
          {{ enumLabel(DAY_STATUS_OPTIONS, detail.day_status) }}
        </p>
        <p>
          当日净额
          <MoneyText :value="detail.totals.net" signed />
          · 单量 {{ detail.totals.order_count }}
        </p>
        <p class="muted">以站点公布为准</p>
      </section>

      <Collapse v-model="active">
        <CollapseItem title="订单列表" name="orders">
          <Empty v-if="!detail.orders.length" description="当日没有订单" />
          <CellGroup v-else inset>
            <Cell
              v-for="order in detail.orders"
              :key="order.id"
              :title="order.order_no"
            >
              <template #value>
                <div>
                  <Tag size="mini" :type="vantTagType(enumColor(ORDER_STATUS_OPTIONS, order.status))">
                    {{ enumLabel(ORDER_STATUS_OPTIONS, order.status) }}
                  </Tag>
                  <div><MoneyText :value="order.amount" /></div>
                </div>
              </template>
              <template #label>
                <p class="muted">
                  {{ toDateTimeString(order.deliver_time || order.order_time) }}
                  · {{ order.distance_km }} 公里 · {{ order.weight_jin }} 斤
                </p>
                <p v-if="order.details.length" class="hits">
                  命中科目：{{ order.details.map((item) => item.subject).join('、') || '无' }}
                </p>
              </template>
            </Cell>
          </CellGroup>
        </CollapseItem>
        <CollapseItem title="奖惩明细" name="adjustments">
          <Empty v-if="!detail.adjustments.length" description="当日没有奖惩" />
          <CellGroup v-else inset>
            <Cell
              v-for="item in detail.adjustments"
              :key="item.id"
              :title="item.subject"
              :label="item.remark || '无备注'"
            >
              <template #value>
                <MoneyText :value="item.amount" signed />
              </template>
            </Cell>
          </CellGroup>
        </CollapseItem>
      </Collapse>
    </div>
  </div>
</template>

<style scoped>
.info {
  padding: 14px;
  margin-bottom: 12px;
}

.info p {
  margin: 0 0 6px;
}

.hits {
  margin-top: 4px;
}
</style>
