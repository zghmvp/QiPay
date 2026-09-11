<script setup lang="ts">
import { computed } from 'vue'
import { formatMoney, formatSigned, isNegativeMoney, isPositiveMoney } from '@/utils/money'
import type { MoneyValue } from '@/types'

const props = withDefaults(
  defineProps<{
    value: MoneyValue
    signed?: boolean
  }>(),
  { signed: false },
)

const text = computed(() =>
  props.signed ? formatSigned(props.value) : formatMoney(props.value),
)
const klass = computed(() => {
  if (isNegativeMoney(props.value)) return 'money-neg'
  if (props.signed && isPositiveMoney(props.value)) return 'money-pos'
  return ''
})
</script>

<template>
  <span class="display-num" :class="klass">{{ text }}</span>
</template>
