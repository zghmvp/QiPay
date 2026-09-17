<script lang="ts" setup>
import type { DashboardCards } from '../../../types/dashboard';

import { computed } from 'vue';
import { useRouter } from 'vue-router';

import { formatMoney } from '../../../utils/money';
import { insightCardTarget } from '../scope-links';

const props = defineProps<{
  cards: DashboardCards;
  month?: string;
  siteId?: null | number;
}>();

const router = useRouter();

const items = [
  {
    key: 'on_job_riders',
    title: '在职骑手',
    value: () => props.cards.on_job_riders,
  },
  {
    key: 'month_order_count',
    title: '本月单量',
    value: () => props.cards.month_order_count,
  },
  {
    key: 'month_valid_order_count',
    title: '有效单量',
    hint: '与本月单量同一订单列表，口径为有效单',
    value: () => props.cards.month_valid_order_count,
  },
  {
    key: 'estimated_gross',
    money: true,
    title: '预计应发',
    value: () => props.cards.estimated_gross,
  },
  {
    key: 'pending_advances',
    title: '待审核预支',
    value: () => props.cards.pending_advances,
  },
  {
    key: 'to_pay_advances',
    title: '待发放预支',
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

function openCard(key: string) {
  const target = insightCardTarget(key, props.siteId, props.month);
  void router.push(target);
}
</script>

<template>
  <div
    v-if="show"
    class="grid grid-cols-2 gap-3 xl:grid-cols-6"
    data-testid="ops-dashboard-insight-card-scope"
  >
    <a-card
      v-for="item in items"
      :key="item.key"
      class="cursor-pointer"
      :data-card-key="item.key"
      :data-testid="`dashboard-insight-card-${item.key}`"
      hoverable
      size="small"
      @click="openCard(item.key)"
    >
      <a-statistic :title="item.title" :value="displayValue(item)" />
      <div
        v-if="'hint' in item && item.hint"
        class="text-muted-foreground mt-1 text-xs"
      >
        {{ item.hint }}
      </div>
    </a-card>
  </div>
</template>
