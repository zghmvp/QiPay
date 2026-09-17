<script lang="ts" setup>
import type { UploadChangeParam, UploadFile } from 'antdv-next';

import type { RecalcJobDetail } from '../../../types/dashboard';
import type { ImportErrorItem, ImportResult } from '../../../types/order';

import { computed, onUnmounted, ref } from 'vue';
import { useRouter } from 'vue-router';

import { useVbenModal } from '@vben/common-ui';
import { IconifyIcon } from '@vben/icons';

import { message } from 'antdv-next';

import {
  getRecalcJobApi,
  retryRecalcJobApi,
} from '../../../api/dashboard';
import { downloadErrorReportApi, importOrdersApi } from '../../../api/order';
import SiteSelect from '../../../components/SiteSelect.vue';
import StatusTag from '../../../components/StatusTag.vue';
import { IMPORT_BATCH_STATUS_OPTIONS } from '../../../constants/enums';

const MAX_SIZE = 10 * 1024 * 1024;
const ACCEPT = '.xlsx,.xls,.csv';
const router = useRouter();

const step = ref(0);
const siteId = ref<number>();
const skipErrors = ref(false);
const autoRecalc = ref(false);
const fileList = ref<UploadFile[]>([]);
const submitting = ref(false);
const result = ref<ImportResult>();
const recalcJob = ref<RecalcJobDetail>();
const retrying = ref(false);
let pollTimer: null | ReturnType<typeof setInterval> = null;

const confirmText = computed(() => {
  if (step.value === 0) return '开始导入';
  if (step.value === 1) return '下一步';
  return '查看本批次订单';
});

const recalcStatusText = computed(() => {
  const job = recalcJob.value;
  if (!job) return '';
  return job.status_label || job.status;
});

const failedPeriodIds = computed(() => {
  const payload = recalcJob.value?.payload;
  const ids = payload?.failed_period_ids ?? [];
  const extra = (payload?.failed ?? [])
    .map((row) => Number(row.period_id))
    .filter((n) => Number.isFinite(n) && n > 0);
  return [...new Set([...ids.map(Number), ...extra].filter((n) => n > 0))];
});

const recalcFailed = computed(() => {
  const job = recalcJob.value;
  if (!job) return false;
  return (
    job.status === 'failed' ||
    (job.failed_rider_count ?? job.payload?.failed_rider_count ?? 0) > 0
  );
});

function goCalcPage(periodId: number) {
  void router.push({ path: `/rider-salary/period/${periodId}/calculate` });
}

const errorColumns = [
  { dataIndex: 'row', title: '行号', width: 80 },
  { dataIndex: 'order_no', title: '订单号' },
  { dataIndex: 'reason', title: '失败原因' },
];

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function refreshRecalcJob(jobId: number) {
  const job = await getRecalcJobApi(jobId);
  recalcJob.value = job;
  if (job.status === 'done' || job.status === 'failed') {
    stopPoll();
  }
  return job;
}

function startPoll(jobId: number) {
  stopPoll();
  void refreshRecalcJob(jobId);
  pollTimer = setInterval(() => {
    void refreshRecalcJob(jobId).catch(() => stopPoll());
  }, 1500);
}

function currentFile(): File | undefined {
  const item = fileList.value[0];
  const raw = item?.originFileObj ?? (item as unknown as File | undefined);
  return raw instanceof File ? raw : undefined;
}

function beforeUpload(file: File) {
  const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
  if (!['.csv', '.xls', '.xlsx'].includes(ext)) {
    message.error('仅支持 Excel 或 CSV 文件');
    return false;
  }
  if (file.size > MAX_SIZE) {
    message.error('文件过大，单次最多 10MB，请拆分后上传');
    return false;
  }
  return false;
}

function onFileChange(info: UploadChangeParam) {
  const last = info.fileList.slice(-1);
  const file = last[0]?.originFileObj;
  if (file && file.size > MAX_SIZE) {
    fileList.value = [];
    return;
  }
  fileList.value = last;
}

async function doImport() {
  if (!siteId.value) {
    message.warning('请选择站点');
    return false;
  }
  const file = currentFile();
  if (!file) {
    message.warning('请上传导入文件');
    return false;
  }
  submitting.value = true;
  modalApi.lock();
  try {
    result.value = await importOrdersApi({
      auto_recalc: autoRecalc.value,
      file,
      site_id: siteId.value,
      skip_errors: skipErrors.value,
    });
    const jobId = result.value?.recalc_job_id;
    if (jobId) {
      startPoll(jobId);
    }
    return true;
  } finally {
    submitting.value = false;
    modalApi.unlock();
  }
}

async function downloadReport() {
  const batchId = result.value?.batch_id;
  if (!batchId) {
    message.warning('当前没有可下载的错误报告');
    return;
  }
  await downloadErrorReportApi(batchId);
}

async function onRetryRecalc() {
  const jobId = recalcJob.value?.id ?? result.value?.recalc_job_id;
  if (!jobId) return;
  retrying.value = true;
  try {
    const job = await retryRecalcJobApi(jobId);
    recalcJob.value = job;
    message.info('已重新排队重算');
    startPoll(job.id);
  } finally {
    retrying.value = false;
  }
}

const [Modal, modalApi] = useVbenModal({
  class: 'w-[760px]',
  confirmText: '开始导入',
  destroyOnClose: true,
  async onConfirm() {
    if (step.value === 0) {
      const ok = await doImport();
      if (!ok) return;
      step.value = 1;
      modalApi.setState({ confirmText: confirmText.value });
      return;
    }
    if (step.value === 1) {
      step.value = 2;
      modalApi.setState({ confirmText: confirmText.value });
      return;
    }
    modalApi
      .getData<{ onSuccess?: (batchId?: null | number) => void }>()
      ?.onSuccess?.(result.value?.batch_id);
    await modalApi.close();
  },
  onOpenChange(isOpen) {
    if (!isOpen) {
      stopPoll();
      return;
    }
    step.value = 0;
    siteId.value = undefined;
    skipErrors.value = false;
    autoRecalc.value = false;
    fileList.value = [];
    result.value = undefined;
    recalcJob.value = undefined;
    modalApi.setState({ confirmText: '开始导入' });
  },
});

onUnmounted(stopPoll);
</script>

<template>
  <Modal title="导入订单">
    <a-steps
      :current="step"
      :items="[
        { title: '选择文件' },
        { title: '导入结果' },
        { title: '完成' },
      ]"
      class="mb-4"
      size="small"
    />
    <div v-if="step === 0" class="flex flex-col gap-3">
      <div>
        <div class="mb-1 text-sm">站点</div>
        <SiteSelect v-model:value="siteId" />
      </div>
      <a-checkbox v-model:checked="skipErrors">跳过错误行</a-checkbox>
      <a-checkbox v-model:checked="autoRecalc">导入后自动重算</a-checkbox>
      <a-alert
        show-icon
        type="info"
        message="默认整批事务：任一行失败则全部回滚。勾选「跳过错误行」后成功行仍会入库。"
      />
      <a-upload-dragger
        v-model:file-list="fileList"
        :accept="ACCEPT"
        :before-upload="beforeUpload"
        :max-count="1"
        @change="onFileChange"
      >
        <p class="flex justify-center py-2">
          <IconifyIcon class="size-10 opacity-60" icon="lucide:upload" />
        </p>
        <p class="ant-upload-text">点击或拖拽文件到此区域</p>
        <p class="ant-upload-hint">支持 xlsx / xls / csv，不超过 10MB</p>
      </a-upload-dragger>
    </div>
    <div v-else-if="step === 1" class="flex flex-col gap-3">
      <a-spin :spinning="submitting" tip="处理中，请勿关闭页面">
        <a-descriptions v-if="result" bordered size="small" :column="2">
          <a-descriptions-item label="状态">
            <StatusTag :options="IMPORT_BATCH_STATUS_OPTIONS" :value="result.status" />
          </a-descriptions-item>
          <a-descriptions-item label="总行数">{{ result.total_rows }}</a-descriptions-item>
          <a-descriptions-item label="成功">{{ result.success_rows }}</a-descriptions-item>
          <a-descriptions-item label="失败">{{ result.failed_rows }}</a-descriptions-item>
        </a-descriptions>
        <a-table
          v-if="result?.errors?.length"
          class="mt-3"
          size="small"
          :columns="errorColumns"
          :data-source="result.errors"
          :pagination="false"
          :row-key="(row: ImportErrorItem) => `${row.row}-${row.order_no}`"
        />
        <a-empty v-else-if="result && result.failed_rows === 0" class="mt-3" description="全部导入成功" />
        <div
          v-if="result && autoRecalc && result.success_rows > 0"
          class="mt-3"
          data-testid="import-recalc-status"
        >
          <a-alert
            v-if="!recalcJob || recalcJob.status === 'queued'"
            show-icon
            type="info"
            :message="`重算状态：${recalcStatusText || '排队中'}`"
            description="导入已入库，正在排队重算。完成前请勿当作已出账。"
          />
          <a-alert
            v-else-if="recalcJob.status === 'running'"
            show-icon
            type="info"
            :message="`重算状态：计算中（${recalcJob.done_periods}/${recalcJob.total_periods}）`"
            :description="recalcJob.message || '正在计算相关开放周期…'"
          />
          <a-alert
            v-else-if="recalcJob.status === 'done' && !recalcFailed"
            show-icon
            type="success"
            message="重算状态：完成"
            :description="recalcJob.message || '相关周期已重算完成'"
          />
          <a-alert
            v-else-if="recalcFailed"
            show-icon
            type="error"
            data-testid="import-recalc-failed"
            :message="`重算状态：${recalcJob.message?.includes('部分失败') ? '部分失败' : '失败'}`"
            :description="recalcJob.message || '重算失败，可到算薪页查看失败清单'"
          />
          <div v-if="recalcFailed && failedPeriodIds.length" class="mt-2 flex flex-wrap gap-2">
            <a-button
              v-for="pid in failedPeriodIds"
              :key="pid"
              size="small"
              data-testid="import-recalc-goto-calc"
              @click="goCalcPage(pid)"
            >
              去算薪页 #{{ pid }}
            </a-button>
          </div>
          <a-button
            v-if="recalcJob?.status === 'failed'"
            class="mt-2"
            :loading="retrying"
            data-testid="import-recalc-retry"
            @click="onRetryRecalc"
          >
            重试重算
          </a-button>
        </div>
        <a-button
          v-if="result?.batch_id && result.failed_rows > 0"
          class="mt-3"
          @click="downloadReport"
        >
          下载完整错误报告
        </a-button>
      </a-spin>
    </div>
    <div v-else class="py-6 text-center">
      <p>导入流程已完成。</p>
      <p
        v-if="recalcJob"
        class="text-muted-foreground mt-2 text-sm"
        data-testid="import-recalc-final"
      >
        重算：{{ recalcStatusText }}
        <template v-if="recalcJob.message">（{{ recalcJob.message }}）</template>
      </p>
      <p v-if="result?.batch_id" class="text-muted-foreground mt-2 text-sm">
        点击下方按钮查看本批次订单
      </p>
    </div>
  </Modal>
</template>
