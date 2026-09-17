<script lang="ts" setup>
import type { VbenFormProps } from '@vben/common-ui';

import type { AdjustmentForm, AdjustmentResult } from '../../types/adjustment';
import type { SubjectResult } from '../../types/subject';

import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';

import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';

import { useVbenDrawer, useVbenModal, VbenButton } from '@vben/common-ui';
import { IconifyIcon, MaterialSymbolsAdd } from '@vben/icons';

import { message } from 'antdv-next';

import { useVbenForm } from '#/adapter/form';
import { useVbenVxeGrid } from '#/adapter/vxe-table';

import {
  createAdjustmentApi,
  deleteAdjustmentApi,
  getAdjustmentListApi,
  updateAdjustmentApi,
} from '../../api/adjustment';
import { getAllSubjectsApi } from '../../api/subject';
import MoneyText from '../../components/MoneyText.vue';
import { useReasonModal } from '../../components/use-reason-modal';
import { toDateString } from '../../utils/date';
import PageContainer from '../_shared/PageContainer.vue';
import BatchModal from './components/BatchModal.vue';
import { adjustmentFormSchema, querySchema, useColumns } from './data';

const route = useRoute();
const { ReasonModal, prompt } = useReasonModal();
const subjects = ref<SubjectResult[]>([]);
getAllSubjectsApi()
  .then((list) => {
    subjects.value = list ?? [];
  })
  .catch(() => undefined);

function queryStr(key: string) {
  const raw = route.query[key];
  const v = Array.isArray(raw) ? raw[0] : raw;
  return typeof v === 'string' && v ? v : undefined;
}

function queryNum(key: string) {
  const n = Number(queryStr(key));
  return Number.isFinite(n) && n > 0 ? n : undefined;
}

const initialSiteId = queryNum('site_id');
const initialRiderId = queryNum('rider_id');
const initialSubjectId = queryNum('subject_id');
const initialId = queryNum('id');
const initialDateFrom = queryStr('date_from');
const initialDateTo = queryStr('date_to');
const initialDateRange =
  initialDateFrom && initialDateTo
    ? [initialDateFrom, initialDateTo]
    : undefined;

const formOptions: VbenFormProps = {
  collapsed: true,
  schema: querySchema.map((item) => {
    if (item.fieldName === 'site_id' && initialSiteId) {
      return { ...item, defaultValue: initialSiteId };
    }
    if (item.fieldName === 'rider_id' && initialRiderId) {
      return { ...item, defaultValue: initialRiderId };
    }
    if (item.fieldName === 'subject_id' && initialSubjectId) {
      return { ...item, defaultValue: initialSubjectId };
    }
    if (item.fieldName === 'date_range' && initialDateRange) {
      return { ...item, defaultValue: initialDateRange };
    }
    return item;
  }),
  showCollapseButton: true,
  submitButtonOptions: { content: '查询' },
};

const gridOptions: VxeTableGridOptions<AdjustmentResult> = {
  columns: useColumns(onActionClick),
  height: 'auto',
  proxyConfig: {
    ajax: {
      query: async ({ page }, formValues) => {
        const { date_range, ...rest } = formValues as {
          date_range?: [string, string];
        };
        return await getAdjustmentListApi({
          date_from: toDateString(date_range?.[0]),
          date_to: toDateString(date_range?.[1]),
          id: initialId,
          page: page.currentPage,
          size: page.pageSize,
          ...rest,
        });
      },
    },
  },
  rowConfig: { keyField: 'id' },
  toolbarConfig: {
    custom: true,
    refresh: true,
    refreshOptions: { code: 'query' },
  },
};

const [Grid, gridApi] = useVbenVxeGrid({ formOptions, gridOptions });

onMounted(async () => {
  const values: Record<string, unknown> = {};
  if (initialSiteId) values.site_id = initialSiteId;
  if (initialRiderId) values.rider_id = initialRiderId;
  if (initialSubjectId) values.subject_id = initialSubjectId;
  if (initialDateRange) values.date_range = initialDateRange;
  if (Object.keys(values).length) {
    await gridApi.formApi.setValues(values);
  }
});

function onRefresh() {
  gridApi.query();
}

async function onActionClick({
  code,
  row,
}: OnActionClickParams<AdjustmentResult>) {
  if (code === 'edit') {
    drawerApi.setData(row).open();
    return;
  }
  if (code === 'delete') {
    const { reason } = await prompt({ title: '删除奖惩原因' });
    await deleteAdjustmentApi(row.id, reason);
    message.success('已删除奖惩');
    onRefresh();
  }
}

const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  schema: adjustmentFormSchema,
  showDefaultActions: false,
});

const formData = ref<{ id?: number }>();
const drawerTitle = computed(() =>
  formData.value?.id ? '编辑奖惩' : '单条录入',
);
const subjectHint = ref('');

const [Drawer, drawerApi] = useVbenDrawer({
  class: 'w-[480px]',
  destroyOnClose: true,
  async onConfirm() {
    const { valid } = await formApi.validate();
    if (!valid) return;
    const values = await formApi.getValues<
      AdjustmentForm & { site_id?: number }
    >();
    drawerApi.lock();
    try {
      if (formData.value?.id) {
        const { reason } = await prompt({ title: '修改奖惩原因' });
        await updateAdjustmentApi(formData.value.id, { ...values, reason });
      } else {
        await createAdjustmentApi(values);
      }
      message.success('操作成功');
      await drawerApi.close();
      onRefresh();
    } finally {
      drawerApi.unlock();
    }
  },
  onOpenChange(isOpen) {
    if (!isOpen) return;
    const data = drawerApi.getData<AdjustmentResult>();
    formApi.resetForm();
    subjectHint.value = '';
    if (data?.id) {
      formData.value = { id: data.id };
      formApi.setValues({ ...data, site_id: data.site_id });
    } else {
      formData.value = undefined;
    }
    formApi.updateSchema([
      {
        componentProps: {
          onChange: (_id: number, row?: SubjectResult) => {
            if (row?.fee_mode === 'fixed' && row.fixed_amount !== null) {
              formApi.setFieldValue('amount', row.fixed_amount);
            }
            subjectHint.value =
              row && !row.include_in_gross
                ? '该科目不计入应发，只减少实发'
                : '';
          },
        },
        fieldName: 'subject_id',
      },
    ]);
  },
});

const [BatchModalComp, batchModalApi] = useVbenModal({
  connectedComponent: BatchModal,
});
</script>

<template>
  <PageContainer>
    <Grid>
      <template #toolbar-actions>
        <VbenButton
          v-access:code="'rs:adjustment:add'"
          class="mr-2"
          @click="() => drawerApi.setData(null).open()"
        >
          <MaterialSymbolsAdd class="size-5" />
          单条录入
        </VbenButton>
        <VbenButton
          v-access:code="'rs:adjustment:add'"
          @click="() => batchModalApi.open()"
        >
          批量录入
        </VbenButton>
      </template>
      <template #locked="{ row }">
        <IconifyIcon
          v-if="row.is_locked"
          class="size-4 text-red-500"
          icon="lucide:lock"
        />
      </template>
      <template #amount="{ row }">
        <MoneyText signed :value="row.signed_amount ?? row.amount" />
      </template>
    </Grid>
    <Drawer :title="drawerTitle">
      <a-alert
        v-if="subjectHint"
        class="mb-3"
        show-icon
        type="info"
        :message="subjectHint"
      />
      <Form />
    </Drawer>
    <BatchModalComp />
    <ReasonModal />
  </PageContainer>
</template>
