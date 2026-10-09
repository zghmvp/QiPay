<script lang="ts" setup>
import type { CostSummary } from '../../types/report';

import { ref, watch } from 'vue';

import { VbenButton } from '@vben/common-ui';

import { getCostSummaryApi } from '../../api/report';
import MoneyText from '../../components/MoneyText.vue';
import SiteSelect from '../../components/SiteSelect.vue';
import { currentMonth } from '../../utils/date';
import PageContainer from '../_shared/PageContainer.vue';

const siteId = ref<null | number>(null);
const month = ref(currentMonth());
const loading = ref(false);
const failed = ref(false);
const summary = ref<CostSummary>();

async function load() {
  loading.value = true;
  failed.value = false;
  try {
    summary.value = await getCostSummaryApi({
      month: month.value,
      site_id: siteId.value ?? undefined,
    });
  } catch {
    summary.value = undefined;
    failed.value = true;
  } finally {
    loading.value = false;
  }
}

watch([siteId, month], () => {
  void load();
});

void load();
</script>

<template>
  <PageContainer>
    <div class="flex min-h-0 flex-1 flex-col overflow-auto">
      <div class="mb-4 flex flex-wrap items-center gap-3">
        <SiteSelect v-model:value="siteId" allow-all />
        <a-date-picker
          v-model:value="month"
          picker="month"
          value-format="YYYY-MM"
        />
        <VbenButton variant="outline" @click="load">刷新</VbenButton>
      </div>

      <a-empty v-if="failed" description="成本报表加载失败，请重试">
        <VbenButton class="mt-2" @click="load">重试</VbenButton>
      </a-empty>
      <a-spin v-else :spinning="loading">
        <a-empty
          v-if="!summary?.rows.length"
          description="该月份暂无成本数据"
        />
        <template v-else>
          <div class="mb-3 flex flex-wrap gap-x-5 text-sm">
            <span>有效单 {{ summary.slip_count }} 张</span>
            <span>应发 <MoneyText :value="summary.gross" /></span>
            <span>实发 <MoneyText :value="summary.net" /></span>
            <span>
              预支抵扣 <MoneyText :value="summary.advance_deduction" />
            </span>
          </div>
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b text-left">
                <th class="py-2 pr-3 font-medium">站点</th>
                <th class="py-2 pr-3 font-medium">月份</th>
                <th class="py-2 pr-3 font-medium">有效单数</th>
                <th class="py-2 pr-3 font-medium">应发</th>
                <th class="py-2 pr-3 font-medium">实发</th>
                <th class="py-2 pr-3 font-medium">预支抵扣</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in summary.rows"
                :key="`${row.site_id}-${row.month}`"
                class="border-b"
              >
                <td class="py-2 pr-3">
                  {{ row.site_name || row.site_code || `站点 #${row.site_id}` }}
                </td>
                <td class="py-2 pr-3">{{ row.month }}</td>
                <td class="py-2 pr-3">{{ row.slip_count }}</td>
                <td class="py-2 pr-3">
                  <MoneyText :value="row.gross" />
                </td>
                <td class="py-2 pr-3">
                  <MoneyText :value="row.net" />
                </td>
                <td class="py-2 pr-3">
                  <MoneyText :value="row.advance_deduction" />
                </td>
              </tr>
            </tbody>
          </table>
        </template>
      </a-spin>
    </div>
  </PageContainer>
</template>
