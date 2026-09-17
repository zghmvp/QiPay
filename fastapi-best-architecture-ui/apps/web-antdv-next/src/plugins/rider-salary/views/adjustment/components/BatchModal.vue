<script lang="ts" setup>
import type { SubjectResult } from '../../../types/subject';

import { ref } from 'vue';

import { useVbenModal } from '@vben/common-ui';

import { message } from 'antdv-next';

import { createAdjustmentBatchApi } from '../../../api/adjustment';
import { getAllSubjectsApi } from '../../../api/subject';
import RiderSelect from '../../../components/RiderSelect.vue';
import SiteSelect from '../../../components/SiteSelect.vue';
import SubjectSelect from '../../../components/SubjectSelect.vue';
import {
  batchSubmitMessage,
  classifyBatchRow,
} from '../batch-rows';

interface BatchRow {
  amount?: number | string;
  biz_date?: string;
  error?: string;
  key: number;
  remark?: string;
  rider_id?: number;
  subject_id?: number;
}

let seq = 1;
const siteId = ref<number>();
const rows = ref<BatchRow[]>([emptyRow()]);
const subjects = ref<SubjectResult[]>([]);

function emptyRow(): BatchRow {
  seq += 1;
  return { key: seq, remark: '' };
}

const columns = [
  { key: 'rider', title: '骑手', width: 180 },
  { key: 'date', title: '日期', width: 160 },
  { key: 'subject', title: '科目', width: 180 },
  { key: 'amount', title: '金额', width: 120 },
  { key: 'remark', title: '备注' },
  { key: 'action', title: '操作', width: 70 },
];

const [Modal, modalApi] = useVbenModal({
  class: 'w-[960px]',
  confirmText: '提交批量录入',
  destroyOnClose: true,
  async onConfirm() {
    const classified = rows.value.map((row) => ({
      kind: classifyBatchRow(row),
      row,
    }));
    const complete = classified.filter((item) => item.kind === 'complete');
    const skipped = classified.filter((item) => item.kind === 'incomplete').length;
    const items = complete.map(({ row }) => ({
      amount: Number(row.amount),
      biz_date: row.biz_date as string,
      remark: row.remark || '',
      rider_id: row.rider_id as number,
      subject_id: row.subject_id as number,
    }));
    if (items.length === 0) {
      message.warning(
        skipped > 0
          ? `没有完整行可录入，跳过未完整 ${skipped} 行`
          : '请至少填写一行完整记录',
      );
      return;
    }
    rows.value = rows.value.map((row) => ({ ...row, error: undefined }));
    modalApi.lock();
    try {
      await createAdjustmentBatchApi(items);
      message.success(batchSubmitMessage(items.length, skipped));
      await modalApi.close();
    } catch (error: unknown) {
      const err = error as {
        msg?: string;
        response?: { data?: { data?: { row?: number }; msg?: string } };
      };
      const msg = err?.response?.data?.msg || err?.msg || '批量录入失败';
      const rowNo = err?.response?.data?.data?.row;
      if (rowNo) {
        const target = items[rowNo - 1];
        const hit = rows.value.find(
          (row) =>
            row.rider_id === target?.rider_id &&
            row.biz_date === target?.biz_date &&
            row.subject_id === target?.subject_id,
        );
        if (hit) hit.error = msg;
      }
    } finally {
      modalApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) return;
    siteId.value = undefined;
    seq = 1;
    rows.value = [emptyRow()];
    subjects.value = (await getAllSubjectsApi().catch(() => [])) ?? [];
  },
});

function addRow() {
  rows.value.push(emptyRow());
}

function removeRow(key: number) {
  rows.value = rows.value.filter((row) => row.key !== key);
  if (rows.value.length === 0) rows.value = [emptyRow()];
}

function onSubjectChange(row: BatchRow, id?: null | number) {
  row.subject_id = id ?? undefined;
  const subject = subjects.value.find((item) => item.id === id);
  if (subject?.fee_mode === 'fixed' && subject.fixed_amount !== null) {
    row.amount = subject.fixed_amount ?? undefined;
  }
}

function rowClassName(record: BatchRow) {
  return record.error ? 'bg-red-50' : '';
}
</script>

<template>
  <Modal title="批量录入奖惩" data-testid="ops-adj-batch-skip-incomplete-not-all-success">
    <div class="mb-3 flex items-center gap-2">
      <span>站点</span>
      <SiteSelect v-model:value="siteId" />
      <a-button type="primary" @click="addRow">新增一行</a-button>
    </div>
    <a-table
      :columns="columns"
      :data-source="rows"
      :pagination="false"
      :row-class-name="rowClassName"
      row-key="key"
      size="small"
    >
      <template #bodyCell="{ column, record }">
        <RiderSelect
          v-if="column.key === 'rider'"
          v-model:value="record.rider_id"
          :site-id="siteId"
        />
        <a-date-picker
          v-else-if="column.key === 'date'"
          v-model:value="record.biz_date"
          class="w-full"
          value-format="YYYY-MM-DD"
        />
        <SubjectSelect
          v-else-if="column.key === 'subject'"
          :value="record.subject_id"
          @change="(id) => onSubjectChange(record, id)"
        />
        <a-input-number
          v-else-if="column.key === 'amount'"
          v-model:value="record.amount"
          class="w-full"
          :precision="2"
        />
        <div v-else-if="column.key === 'remark'">
          <a-input v-model:value="record.remark" />
          <div v-if="record.error" class="mt-1 text-xs text-red-500">
            {{ record.error }}
          </div>
        </div>
        <a-button
          v-else-if="column.key === 'action'"
          type="link"
          danger
          size="small"
          @click="removeRow(record.key)"
        >
          删除
        </a-button>
      </template>
    </a-table>
  </Modal>
</template>
