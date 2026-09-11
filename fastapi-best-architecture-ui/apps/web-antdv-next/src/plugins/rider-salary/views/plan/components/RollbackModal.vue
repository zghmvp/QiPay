<script lang="ts" setup>
import type { RollbackPreviewResult } from '../../../types/plan';

import { computed, ref } from 'vue';

import { useVbenModal } from '@vben/common-ui';

import { message } from 'antdv-next';

import {
  getPlanVersionListApi,
  getRollbackPreviewApi,
  rollbackPlanVersionApi,
} from '../../../api/plan';

const CONFIRM_TEXT = '确认回退';

const loading = ref(false);
const preview = ref<RollbackPreviewResult>();
const reason = ref('');
const confirmText = ref('');

const [Modal, modalApi] = useVbenModal({
  class: 'w-[640px]',
  confirmText: '执行回退',
  destroyOnClose: true,
  async onConfirm() {
    const pk = versionId.value;
    if (!pk) return;
    if (!reason.value.trim()) {
      message.warning('请填写操作原因');
      return;
    }
    if (confirmText.value !== CONFIRM_TEXT) {
      message.warning('请输入确认文字「确认回退」');
      return;
    }
    modalApi.lock();
    try {
      await rollbackPlanVersionApi(pk, {
        confirm_text: confirmText.value,
        reason: reason.value.trim(),
      });
      const planId = modalApi.getData<{ planId?: number }>()?.planId;
      let newId: number | undefined;
      if (planId) {
        const page = await getPlanVersionListApi({
          page: 1,
          plan_id: planId,
          size: 50,
          status: 'draft',
        });
        newId = [...(page?.items ?? [])]
          .filter((item) => item.copied_from_id === pk)
          .sort((a, b) => b.version_no - a.version_no)[0]?.id;
      }
      message.success(
        `回退完成，已为你复制草稿${newId ? '' : ''}，请修改后重新试算启用`,
      );
      modalApi.getData<{ onSuccess?: (id?: number) => void }>()?.onSuccess?.(newId);
      await modalApi.close();
    } finally {
      modalApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) return;
    reason.value = '';
    confirmText.value = '';
    preview.value = undefined;
    const pk = versionId.value;
    if (!pk) return;
    loading.value = true;
    try {
      preview.value = await getRollbackPreviewApi(pk);
    } finally {
      loading.value = false;
    }
  },
});

const versionId = computed(
  () => modalApi.getData<{ versionId?: number }>()?.versionId,
);

const canSubmit = computed(
  () => Boolean(reason.value.trim()) && confirmText.value === CONFIRM_TEXT,
);
</script>

<template>
  <Modal title="确认回退方案版本">
    <a-spin :spinning="loading">
      <div class="flex flex-col gap-3">
        <a-alert
          v-if="preview?.has_paid"
          type="error"
          show-icon
          message="该方案已执行发薪操作，回退将产生财务影响"
        />
        <div class="text-sm leading-6">
          该操作不可撤销，将产生以下后果：
          <ol class="mt-2 list-decimal pl-5">
            <li>
              方案版本「{{ preview?.version_label }}」将作废；
            </li>
            <li>将解除 {{ preview?.binding_count ?? 0 }} 条骑手绑定；</li>
            <li>
              将作废 {{ preview?.payrolls_draft ?? 0 }} 条草稿薪资结果，并标记需重算；
            </li>
            <li v-if="preview?.has_paid || (preview?.payrolls_finalized ?? 0) > 0">
              此外将对 {{ preview?.payrolls_paid ?? 0 }} 条已发薪结果、{{
                preview?.payrolls_finalized ?? 0
              }}
              条已定稿结果生成反冲单，所属周期进入「补发中」。导出将出现原单 / 反冲 / 补发三行。
            </li>
            <li>系统将自动复制一份新草稿版本供修改后重新试算启用。</li>
          </ol>
        </div>
        <div v-if="preview?.riders?.length">
          <div class="mb-1 text-sm font-medium">将被解绑的骑手</div>
          <a-table
            :data-source="preview.riders"
            :pagination="false"
            row-key="rider_id"
            size="small"
          >
            <a-table-column data-index="job_no" title="工号" />
            <a-table-column data-index="name" title="姓名" />
            <a-table-column data-index="start_date" title="开始" />
            <a-table-column data-index="end_date" title="结束" />
          </a-table>
        </div>
        <a-textarea
          v-model:value="reason"
          :rows="3"
          placeholder="请说明回退原因"
        />
        <div>
          <div class="mb-1 text-sm">请输入「确认回退」</div>
          <a-input v-model:value="confirmText" placeholder="确认回退" />
        </div>
        <div class="text-muted-foreground text-xs">
          未输入或输入错误将无法执行。当前{{ canSubmit ? '可提交' : '不可提交' }}。
        </div>
      </div>
    </a-spin>
  </Modal>
</template>
