<script lang="ts" setup>
import type { DashboardCards } from '../../../types/dashboard';

import { computed } from 'vue';
import { useRouter } from 'vue-router';

import { formatMoney } from '../../../utils/money';

const props = defineProps<{
  cards: DashboardCards;
}>();

const router = useRouter();

const items = [
  {
    key: 'on_job_riders',
    title: '在职骑手',
    to: '/rider-salary/rider?status=on_job',
    value: () => props.cards.on_job_riders,
  },
  {
    key: 'month_order_count',
    title: '本月单量',
    to: '/rider-salary/order',
    value: () => props.cards.month_order_count,
  },
  {
    key: 'month_valid_order_count',
    title: '有效单量',
    to: '/rider-salary/order',
    value: () => props.cards.month_valid_order_count,
  },
  {
    key: 'estimated_gross',
    money: true,
    title: '预计应发',
    to: '/rider-salary/period',
    value: () => props.cards.estimated_gross,
  },
  {
    key: 'pending_advances',
    title: '待审核预支',
    to: '/rider-salary/advance?status=pending',
    value: () => props.cards.pending_advances,
  },
  {
    key: 'to_pay_advances',
    title: '待发放预支',
    to: '/rider-salary/advance?status=to_pay',
    value: () => props.cards.to_pay_advances,
  },
] as const;

const show = computed(() =>
  items.some((item) => Number(item.value() ?? 0) !== 0),
);
function displayValue(item: (typeof items)[number]) {
  if ('money' in item && item.money) return formatMoney(item.value());
  return Number(item.value() ?? 0);
}
</script>

<template>
  <div v-if="show" class="grid grid-cols-2 gap-3 xl:grid-cols-6">
    <a-card
      v-for="item in items"
      :key="item.key"
      class="cursor-pointer"
      hoverable
      size="small"
      @click="router.push(item.to)"
    >
      <a-statistic :title="item.title" :value="displayValue(item)" />
    </a-card>
  </div>
</template>
