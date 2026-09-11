<script lang="ts" setup>
import type { CalendarMonthSummary } from '../../../types/calendar';

import { useRouter } from 'vue-router';

import MoneyText from '../../../components/MoneyText.vue';
import {
  enumColor,
  enumLabel,
  PERIOD_STATUS_OPTIONS,
} from '../../../constants/enums';

const props = defineProps<{
  summary?: CalendarMonthSummary;
}>();

const router = useRouter();

function openPeriod(id: number) {
  router.push({ path: '/rider-salary/period', query: { id: String(id) } });
}
</script>

<template>
  <div v-if="summary" class="flex flex-col gap-3">
    <div class="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-7">
      <a-card size="small">
        <div class="text-muted-foreground text-xs">本月累计单量</div>
        <div class="text-lg font-medium">
          {{ summary.order_count }}
          <span class="text-muted-foreground text-xs font-normal">
            有效 {{ summary.valid_order_count }}
          </span>
        </div>
      </a-card>
      <a-card size="small">
        <div class="text-muted-foreground text-xs">应发</div>
        <div class="text-lg font-medium">
          <MoneyText :value="summary.gross" />
        </div>
      </a-card>
      <a-card size="small">
        <div class="text-muted-foreground text-xs">奖</div>
        <div class="text-lg font-medium">
          <MoneyText signed :value="summary.bonus" />
        </div>
      </a-card>
      <a-card size="small">
        <div class="text-muted-foreground text-xs">惩</div>
        <div class="text-lg font-medium">
          <MoneyText signed :value="summary.penalty" />
        </div>
      </a-card>
      <a-card size="small">
        <div class="text-muted-foreground text-xs">代扣</div>
        <div class="text-lg font-medium">
          <MoneyText :value="summary.deduction_total" />
        </div>
      </a-card>
      <a-card size="small">
        <div class="text-muted-foreground text-xs">预支抵扣</div>
        <div class="text-lg font-medium">
          <MoneyText :value="summary.advance_deduction" />
        </div>
      </a-card>
      <a-card size="small">
        <div class="text-muted-foreground text-xs">实发</div>
        <div class="text-lg font-medium">
          <MoneyText :value="summary.net" />
        </div>
      </a-card>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <span class="text-muted-foreground text-sm">涉及周期</span>
      <a-tag
        v-for="chip in summary.periods"
        :key="chip.id"
        class="cursor-pointer"
        :color="enumColor(PERIOD_STATUS_OPTIONS, chip.status)"
        @click="openPeriod(chip.id)"
      >
        {{ chip.range }}
        {{ enumLabel(PERIOD_STATUS_OPTIONS, chip.status) }}
      </a-tag>
      <a-tag v-if="summary.stale" color="red">需重算</a-tag>
    </div>
  </div>
</template>
