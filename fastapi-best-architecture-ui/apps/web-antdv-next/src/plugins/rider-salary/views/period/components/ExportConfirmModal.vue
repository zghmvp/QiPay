<script lang="ts" setup>
import type { ExportConfirmOptions, ExportConfirmResult } from './export-confirm-types';

import { computed, ref } from 'vue';

import { useVbenModal } from '@vben/common-ui';

import { message } from 'antdv-next';

import { loadExportAdjustStats } from './export-adjust-stats';

const title = ref('导出周期薪资');
const attentionCount = ref(0);
const bookedCount = ref(0);
const unbookedCount = ref(0);
const syncDropCount = ref(0);
const attentionLoading = ref(false);
const attentionError = ref('');
const excludeAttention = ref(false);
const excludeAttentionAdjustments = ref(false);
const confirmed = ref(false);

const [Modal, modalApi] = useVbenModal({
  class: 'w-[560px]',
  confirmText: '确认导出',
  destroyOnClose: true,
  async onConfirm() {
    if (attentionLoading.value) {
      message.warning('正在统计需关注条数');
      return;
    }
    const data = modalApi.getData<{
      reject?: (err?: unknown) => void;
      resolve?: (value: ExportConfirmResult) => void;
    }>();
    confirmed.value = true;
    data?.resolve?.({
      attentionCount: attentionCount.value,
      bookedAdjustmentCount: bookedCount.value,
      excludeAttention: excludeAttention.value,
      excludeAttentionAdjustments: excludeAttentionAdjustments.value,
      syncDropCount: syncDropCount.value,
      unbookedAdjustmentCount: unbookedCount.value,
    });
    await modalApi.close();
  },
  onOpenChange(isOpen) {
    if (!isOpen) {
      if (!confirmed.value) {
        modalApi.getData<{ reject?: (err?: unknown) => void }>()?.reject?.(
          new Error('cancelled'),
        );
      }
      return;
    }
    const data = modalApi.getData<ExportConfirmOptions>();
    confirmed.value = false;
    excludeAttention.value = false;
    excludeAttentionAdjustments.value = false;
    attentionCount.value = 0;
    bookedCount.value = 0;
    unbookedCount.value = 0;
    syncDropCount.value = 0;
    attentionError.value = '';
    title.value = data?.title || '导出周期薪资';
    if (!data) {
      attentionError.value = '缺少站点或周期日期，无法统计需关注条数';
      return;
    }
    attentionLoading.value = true;
    void loadStats(data).finally(() => {
      attentionLoading.value = false;
    });
  },
});

async function loadStats(data: ExportConfirmOptions) {
  try {
    const stats = await loadExportAdjustStats(data);
    attentionCount.value = stats.attentionCount;
    bookedCount.value = stats.bookedCount;
    unbookedCount.value = stats.unbookedCount;
    syncDropCount.value = stats.syncDropCount;
  } catch {
    attentionError.value = '需关注条数暂时无法获取，默认不排除。';
    attentionCount.value = 0;
  }
}

const admitCopy = computed(
  () => `本文件含需关注 ${attentionCount.value} 条。排除只影响文件行，不改应发/实发，也不是打款文件。`,
);
</script>

<template>
  <Modal :title="title">
    <div class="flex flex-col gap-3" data-testid="period-export-confirm">
      <a-spin :spinning="attentionLoading">
        <div data-testid="period-export-attention-count">
          本周期需关注订单 <strong>{{ attentionCount }}</strong> 条
          （异常 ∪ 退款 ∪ 超时>60 分钟，与工作台同源，当前筛选范围为该周期日期）。
        </div>
        <div class="mt-2" data-testid="period-export-adj-booked">
          奖惩已入账 <strong>{{ bookedCount }}</strong> 条
        </div>
        <div data-testid="period-export-adj-unbooked">
          窗口内未入账奖惩 <strong>{{ unbookedCount }}</strong> 条（不得冒充已出账）
        </div>
      </a-spin>
      <a-alert
        v-if="attentionError"
        type="warning"
        show-icon
        :message="attentionError"
      />
      <div class="flex items-center gap-2">
        <a-switch
          :checked="excludeAttention"
          data-testid="period-export-exclude-toggle"
          @update:checked="(v) => (excludeAttention = Boolean(v))"
        />
        <span>导出时排除需关注订单</span>
      </div>
      <a-alert
        v-if="!excludeAttention"
        type="warning"
        show-icon
        data-testid="period-export-admit-attention"
        :message="admitCopy"
      />
      <a-alert
        v-else
        type="info"
        show-icon
        message="将从导出文件中排除上述需关注订单。应发/实发金额不变，排除不是锁账条件。"
      />
      <div
        class="text-sm text-muted-foreground"
        data-testid="period-export-adj-annotation"
      >
        默认仍导出全部奖惩。该骑手该日存在需关注订单的奖惩行会标注「该骑手该日存在需关注订单」，不会默认删除。
      </div>
      <div class="flex items-center gap-2">
        <a-switch
          :checked="excludeAttentionAdjustments"
          data-testid="period-export-adj-sync-toggle"
          @update:checked="(v) => (excludeAttentionAdjustments = Boolean(v))"
        />
        <span>奖惩同步去掉同日同骑手</span>
      </div>
      <a-alert
        v-if="excludeAttentionAdjustments"
        type="warning"
        show-icon
        data-testid="period-export-adj-sync-drop-count"
        :message="`奖惩记录将少 ${syncDropCount} 条（与需关注同日同骑手）。`"
      />
      <a-alert
        v-else
        type="info"
        show-icon
        data-testid="period-export-adj-admit"
        message="奖惩记录含与需关注同日同骑手的行。默认仍导出全部奖惩。"
      />
    </div>
  </Modal>
</template>
