<script lang="ts" setup>
import type { ReasonPromptOptions, ReasonResult } from './reason-types';

import { ref } from 'vue';

import dayjs from 'dayjs';

import { useVbenModal } from '@vben/common-ui';

import { message } from 'antdv-next';

const reason = ref('');
const password = ref('');
const title = ref('请填写操作原因');
const extraHint = ref('');
const needPassword = ref(false);
const passwordRequired = ref(false);
const reasonRequired = ref(true);
const withDate = ref(false);
const dateLabel = ref('生效日期');
const dateValue = ref('');
const confirmed = ref(false);

const [Modal, modalApi] = useVbenModal({
  class: 'w-[480px]',
  confirmText: '确定',
  destroyOnClose: true,
  async onConfirm() {
    if (reasonRequired.value && !reason.value.trim()) {
      message.warning('请填写操作原因');
      return;
    }
    if (needPassword.value && passwordRequired.value && !password.value) {
      message.warning('请填写密码');
      return;
    }
    if (withDate.value && !dateValue.value) {
      message.warning(`请选择${dateLabel.value}`);
      return;
    }
    const data = modalApi.getData<{
      reject?: (err?: unknown) => void;
      resolve?: (value: ReasonResult) => void;
    }>();
    confirmed.value = true;
    data?.resolve?.({
      date: withDate.value ? dateValue.value : undefined,
      password: needPassword.value ? password.value || undefined : undefined,
      reason: reason.value.trim(),
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
    const data = modalApi.getData<
      ReasonPromptOptions & {
        reject?: (err?: unknown) => void;
        resolve?: (value: ReasonResult) => void;
      }
    >();
    confirmed.value = false;
    reason.value = '';
    password.value = '';
    title.value = data?.title || '请填写操作原因';
    extraHint.value = data?.extraHint || '';
    needPassword.value = Boolean(data?.password);
    passwordRequired.value = Boolean(data?.passwordRequired);
    reasonRequired.value = data?.reasonRequired !== false;
    withDate.value = Boolean(data?.withDate);
    dateLabel.value = data?.dateLabel || '生效日期';
    dateValue.value = dayjs().format('YYYY-MM-DD');
  },
});
</script>

<template>
  <Modal :title="title">
    <div class="flex flex-col gap-3">
      <a-alert v-if="extraHint" type="info" show-icon :message="extraHint" />
      <a-textarea
        v-model:value="reason"
        :placeholder="reasonRequired ? '请填写操作原因' : '操作原因（可选）'"
        :rows="4"
      />
      <a-input-password
        v-if="needPassword"
        v-model:value="password"
        :placeholder="passwordRequired ? '请输入密码' : '密码（可选，不填则按规则生成）'"
      />
      <div v-if="withDate" class="flex items-center gap-2">
        <span class="shrink-0">{{ dateLabel }}</span>
        <a-date-picker
          v-model:value="dateValue"
          class="flex-1"
          value-format="YYYY-MM-DD"
          :allow-clear="false"
        />
      </div>
    </div>
  </Modal>
</template>
