<script lang="ts" setup>
import type { EchartsUIType } from '@vben/plugins/echarts';

import type { DashboardTrendPoint } from '../../../types/dashboard';

import { onMounted, ref, watch } from 'vue';

import { EchartsUI, useEcharts } from '@vben/plugins/echarts';

import { formatMoney } from '../../../utils/money';

const props = defineProps<{
  data: DashboardTrendPoint[];
}>();

const chartRef = ref<EchartsUIType>();
const { renderEcharts } = useEcharts(chartRef);

function render() {
  const points = props.data ?? [];
  if (!points.length) return;
  renderEcharts({
    grid: { bottom: 24, containLabel: true, left: 48, right: 56, top: 40 },
    legend: { data: ['单量', '逐单金额'] },
    series: [
      {
        data: points.map((item) => item.order_count),
        name: '单量',
        type: 'line',
      },
      {
        data: points.map((item) => Number(item.formula_amount ?? 0)),
        name: '逐单金额',
        type: 'line',
        yAxisIndex: 1,
      },
    ],
    tooltip: { trigger: 'axis' },
    xAxis: {
      data: points.map((item) => String(item.date).slice(5, 10)),
      type: 'category',
    },
    yAxis: [
      { name: '单量', type: 'value' },
      {
        axisLabel: {
          formatter: (value: number) => formatMoney(value),
        },
        name: '逐单金额',
        type: 'value',
      },
    ],
  });
}

onMounted(render);
watch(() => props.data, render, { deep: true });
</script>

<template>
  <a-card size="small" title="近 30 天趋势">
    <EchartsUI ref="chartRef" height="320px" />
  </a-card>
</template>
