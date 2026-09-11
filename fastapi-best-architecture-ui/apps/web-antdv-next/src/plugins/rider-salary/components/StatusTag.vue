<script lang="ts" setup>
import type { EnumOption } from '../constants/enums';

import { computed } from 'vue';

import { enumColor, enumLabel } from '../constants/enums';

const props = defineProps<{
  options: EnumOption[];
  value?: null | number | string;
}>();

const label = computed(() => enumLabel(props.options, props.value));
const color = computed(() => enumColor(props.options, props.value));
</script>

<template>
  <a-tag :color="color">{{ label }}</a-tag>
</template>
