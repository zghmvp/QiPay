<script lang="ts" setup>
import type { ExportConfirmOptions, ExportConfirmResult } from './export-confirm-types';

import { computed, ref } from 'vue';

import { useVbenModal } from '@vben/common-ui';

import { message } from 'antdv-next';

import { getOrderListApi } from '../../../api/order';
import { getPeriodApi } from '../../../api/period';

const title = ref('导出周期薪资');
const attentionCount = ref(0);
const attentionLoading = ref(false);
const attentionError = ref('');
const excludeAttention = ref(false);
const confirmed = ref(false);

const [Modal, modalApi] = useVbenModal({
  class: 'w-[520px]',
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
      excludeAttention: excludeAttention.value,
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
    attentionCount.value = 0;
    attentionError.value = '';
    title.value = data?.title || '导出周期薪资';
    if (!data) {
      attentionError.value = '缺少站点或周期日期，无法统计需关注条数';
      return;
    }
    attentionLoading.value = true;
    void loadAttentionCount(data).finally(() => {
      attentionLoading.value = false;
    });
  },
});

async function loadAttentionCount(data: ExportConfirmOptions) {
  if (data.periodId) {
    try {
      const period = await getPeriodApi(data.periodId);
      if (typeof period.attention_order_count === 'number') {
        attentionCount.value = period.attention_order_count;
        return;
      }
    } catch {
      /* 回退订单 attention 计数 */
    }
  }
  if (!data.siteId || !data.dateFrom || !data.dateTo) {
    attentionError.value = '缺少站点或周期日期，无法统计需关注条数';
    return;
  }
  try {
    const res = await getOrderListApi({
      attention: true,
      date_from: data.dateFrom,
      date_to: data.dateTo,
      page: 1,
      site_id: data.siteId,
      size: 1,
    });
    attentionCount.value = Number(res?.total ?? 0) || 0;
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
    </div>
  </Modal>
</template>
