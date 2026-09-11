<script lang="ts" setup>
import StatusTag from '../../../components/StatusTag.vue';
import { PLAN_VERSION_STATUS_OPTIONS } from '../../../constants/enums';

defineProps<{
  value?: null | string;
}>();
</script>

<template>
  <StatusTag :options="PLAN_VERSION_STATUS_OPTIONS" :value="value" />
</template>
