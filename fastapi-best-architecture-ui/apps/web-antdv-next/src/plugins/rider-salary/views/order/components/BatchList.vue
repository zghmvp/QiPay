<script lang="ts" setup>
import type { ImportBatchResult } from '../../../types/order';

import { ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { message } from 'antdv-next';

import {
  downloadErrorReportApi,
  getImportBatchListApi,
} from '../../../api/order';
import SiteSelect from '../../../components/SiteSelect.vue';
import StatusTag from '../../../components/StatusTag.vue';
import {
  enumTagOptions,
  IMPORT_BATCH_STATUS_OPTIONS,
} from '../../../constants/enums';

const siteId = ref<number>();
const status = ref<string>();
const loading = ref(false);
const items = ref<ImportBatchResult[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(10);

const columns = [
  { dataIndex: 'id', title: '批次', width: 80 },
  { dataIndex: 'file_name', title: '文件名', ellipsis: true },
  { dataIndex: 'site_name', title: '站点', width: 120 },
  { dataIndex: 'status', key: 'status', title: '状态', width: 110 },
  { dataIndex: 'success_rows', title: '成功', width: 80 },
  { dataIndex: 'failed_rows', title: '失败', width: 80 },
  { dataIndex: 'created_time', title: '导入时间', width: 170 },
  { key: 'action', title: '操作', width: 140 },
];

async function load() {
  loading.value = true;
  try {
    const res = await getImportBatchListApi({
      page: page.value,
      site_id: siteId.value,
      size: pageSize.value,
      status: status.value,
    });
    items.value = res?.items ?? [];
    total.value = res?.total ?? 0;
  } finally {
    loading.value = false;
  }
}

async function downloadReport(row: ImportBatchResult) {
  if (!row.failed_rows) {
    message.warning('该批次没有错误报告');
    return;
  }
  await downloadErrorReportApi(row.id);
}

function onFilter() {
  page.value = 1;
  load();
}

function onPageChange(nextPage: number, nextSize: number) {
  page.value = nextPage;
  pageSize.value = nextSize;
  load();
}

const [Drawer] = useVbenDrawer({
  class: 'w-[880px]',
  cancelText: '关闭',
  destroyOnClose: true,
  showConfirmButton: false,
  onOpenChange(isOpen) {
    if (!isOpen) return;
    siteId.value = undefined;
    status.value = undefined;
    page.value = 1;
    load();
  },
});
</script>

<template>
  <Drawer title="导入批次">
    <div class="mb-3 flex flex-wrap gap-2">
      <SiteSelect v-model:value="siteId" @change="onFilter" />
      <a-select
        v-model:value="status"
        allow-clear
        class="min-w-[140px]"
        placeholder="批次状态"
        :options="enumTagOptions(IMPORT_BATCH_STATUS_OPTIONS)"
        @change="onFilter"
      />
    </div>
    <a-table
      :columns="columns"
      :data-source="items"
      :loading="loading"
      :pagination="{
        current: page,
        onChange: onPageChange,
        pageSize,
        showSizeChanger: true,
        total,
      }"
      :row-key="(row: ImportBatchResult) => row.id"
      size="small"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'status'">
          <StatusTag :options="IMPORT_BATCH_STATUS_OPTIONS" :value="record.status" />
        </template>
        <template v-else-if="column.key === 'action'">
          <a-button
            type="link"
            size="small"
            :disabled="!record.failed_rows"
            @click="downloadReport(record)"
          >
            错误报告
          </a-button>
        </template>
      </template>
    </a-table>
  </Drawer>
</template>
