<script lang="ts" setup>
import type { MoneyValue } from '../types/common';

import { computed } from 'vue';

import { formatMoney, formatSigned, isNegativeMoney } from '../utils/money';

const props = withDefaults(
  defineProps<{
    signed?: boolean;
    value?: MoneyValue;
  }>(),
  { signed: false, value: undefined },
);

const text = computed(() =>
  props.signed ? formatSigned(props.value) : formatMoney(props.value),
);
const negative = computed(() => isNegativeMoney(props.value));
</script>

<template>
  <span :class="negative ? 'text-red-500' : ''">{{ text }}</span>
</template>
