<script lang="ts" setup>
import type { PeriodResult } from '../../../types/period';
import type { RiderResult } from '../../../types/rider';
import type { RiderSelectOption } from '../rider-search';

import { computed, ref, watch } from 'vue';

import { useVbenModal } from '@vben/common-ui';

import { message } from 'antdv-next';

import { calculatePeriodApi, getCalcJobApi } from '../../../api/period';
import {
  calcProgressText,
  describeCalcJob,
  waitForCalcJob,
} from '../calc-progress';
import { getRiderListApi } from '../../../api/rider';
import {
  buildRiderSearchQuery,
  mergeRiderOptions,
  pinSelectedRiders,
  toRiderOption,
} from '../rider-search';

const riderIds = ref<number[]>([]);
const fetchedOptions = ref<RiderSelectOption[]>([]);
const pinnedOptions = ref<RiderSelectOption[]>([]);
const loading = ref(false);
const progressText = ref('');
const personal = ref(false);
const reopened = ref(false);
const siteId = ref<number>();

let searchTimer: null | ReturnType<typeof setTimeout> = null;
let requestSeq = 0;

const options = computed(() =>
  mergeRiderOptions(pinnedOptions.value, fetchedOptions.value),
);

function rememberSelected(ids: number[]) {
  pinnedOptions.value = pinSelectedRiders(ids, [
    ...pinnedOptions.value,
    ...fetchedOptions.value,
  ]);
}

async function loadRiders(keyword?: string) {
  if (!siteId.value) {
    fetchedOptions.value = [];
    return;
  }
  const seq = ++requestSeq;
  loading.value = true;
  try {
    const res = await getRiderListApi(
      buildRiderSearchQuery({ keyword, siteId: siteId.value }),
    );
    if (seq !== requestSeq) return;
    fetchedOptions.value = (res?.items ?? []).map((item: RiderResult) =>
      toRiderOption(item),
    );
  } finally {
    if (seq === requestSeq) loading.value = false;
  }
}

function onSearch(value: string) {
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    void loadRiders(value);
  }, 300);
}

watch(riderIds, (ids) => {
  rememberSelected(ids ?? []);
});

const [Modal, modalApi] = useVbenModal({
  class: 'w-[480px]',
  confirmText: '开始算薪',
  destroyOnClose: true,
  async onConfirm() {
    const period = modalApi.getData<PeriodResult & { onSuccess?: () => void }>();
    if (!period?.id) return;
    modalApi.lock();
    try {
      const res = await calculatePeriodApi(period.id, {
        rider_ids: riderIds.value.length ? riderIds.value : null,
      });
      progressText.value = '';
      if (res.queued && res.job_id) {
        const job = await waitForCalcJob(res.job_id, getCalcJobApi, {
          onTick: (item) => {
            progressText.value = calcProgressText(item);
          },
        });
        const outcome = describeCalcJob(job);
        message[outcome.level](outcome.text);
        if (job.warnings?.length) {
          message.warning(job.warnings.join('；'));
        }
      } else if (res.queued) {
        message.info('算薪已转入后台处理');
      } else {
        message.success(`已计算 ${res.calculated} 名骑手`);
        if (res.warnings?.length) {
          message.warning(res.warnings.join('；'));
        }
      }
      period.onSuccess?.();
      await modalApi.close();
    } finally {
      modalApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) {
      if (searchTimer) clearTimeout(searchTimer);
      requestSeq += 1;
      return;
    }
      riderIds.value = [];
      fetchedOptions.value = [];
      pinnedOptions.value = [];
      progressText.value = '';
    personal.value = false;
    reopened.value = false;
    siteId.value = undefined;
    const period = modalApi.getData<PeriodResult>();
    reopened.value = period?.status === 'reopened';
    if (!period?.site_id) return;
    siteId.value = period.site_id;
    if (period.rider_id) {
      personal.value = true;
      const label = [period.rider_job_no, period.rider_name]
        .filter(Boolean)
        .join(' ');
      pinnedOptions.value = [
        { label: label || String(period.rider_id), value: period.rider_id },
      ];
      riderIds.value = [period.rider_id];
    }
    await loadRiders();
  },
});
</script>

<template>
  <Modal title="计算周期薪资">
    <a-alert
      v-if="reopened"
      class="mb-3"
      show-icon
      type="warning"
      message="本周期处于补发中。方案回退会把整期已定稿且尚未反冲的薪资单一并反冲，请计算全部骑手以生成补发单。原单尚未反冲的骑手不能生成补发；只算部分骑手时，其余缺补发单的人将无法锁账。"
    />
    <a-alert
      v-else
      class="mb-3"
      show-icon
      type="info"
      message="输入工号或姓名搜索骑手。不选则计算周期内全部骑手。个性化周期骑手不会写入站点级结果。"
    />
    <p v-if="progressText" class="mb-3">{{ progressText }}</p>
    <a-select
      v-model:value="riderIds"
      allow-clear
      class="w-full"
      mode="multiple"
      placeholder="输入工号或姓名搜索，留空则计算全部骑手"
      :disabled="personal"
      :filter-option="false"
      :loading="loading"
      :options="options"
      show-search
      @search="onSearch"
    />
  </Modal>
</template>
