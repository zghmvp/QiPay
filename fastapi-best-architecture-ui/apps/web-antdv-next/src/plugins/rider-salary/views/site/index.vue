<script lang="ts" setup>
import type { VbenFormProps } from '@vben/common-ui';

import type { SiteForm, SiteResult } from '../../types/site';

import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';

import { computed, ref } from 'vue';

import { confirm, useVbenDrawer, VbenButton } from '@vben/common-ui';
import { MaterialSymbolsAdd } from '@vben/icons';

import { message } from 'antdv-next';

import { useVbenForm } from '#/adapter/form';
import { useVbenVxeGrid } from '#/adapter/vxe-table';

import {
  createSiteApi,
  deleteSiteApi,
  getSiteListApi,
  updateSiteApi,
} from '../../api/site';
import MoneyText from '../../components/MoneyText.vue';
import PageContainer from '../_shared/PageContainer.vue';
import ManagerCountCell from './components/ManagerCountCell.vue';
import ManagerDrawer from './components/ManagerDrawer.vue';
import { querySchema, siteFormSchema, useColumns } from './data';
import { normalizeMonthlyAdvanceLimit } from './helpers';
import { invalidateManagerCount } from './manager-count-cache';

const formOptions: VbenFormProps = {
  collapsed: true,
  schema: querySchema,
  showCollapseButton: true,
  submitButtonOptions: { content: '查询' },
};

const gridOptions: VxeTableGridOptions<SiteResult> = {
  columns: useColumns(onActionClick),
  height: 'auto',
  proxyConfig: {
    ajax: {
      query: async ({ page }, formValues) => {
        return await getSiteListApi({
          page: page.currentPage,
          size: page.pageSize,
          ...formValues,
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

function onRefresh() {
  gridApi.query();
}

function onActionClick({ code, row }: OnActionClickParams<SiteResult>) {
  if (code === 'edit') {
    drawerApi.setData(row).open();
    return;
  }
  if (code === 'managers') {
    managerDrawerApi
      .setData({
        id: row.id,
        onSuccess: () => {
          invalidateManagerCount(row.id);
          onRefresh();
        },
      })
      .open();
    return;
  }
  if (code === 'delete') {
    deleteSiteApi(row.id).then(() => {
      message.success(`已删除站点 ${row.name}`);
      onRefresh();
    });
  }
}

const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  schema: siteFormSchema,
  showDefaultActions: false,
});

const formData = ref<{ id?: number }>();
const drawerTitle = computed(() => (formData.value?.id ? '编辑站点' : '新增站点'));

const [Drawer, drawerApi] = useVbenDrawer({
  class: 'w-[480px]',
  destroyOnClose: true,
  async onConfirm() {
    const { valid } = await formApi.validate();
    if (!valid) return;
    const values = await formApi.getValues<
      SiteForm & { anchor_day?: number }
    >();
    if (values.status === 'disable' && formData.value?.id) {
      await confirm({
        content:
          '停用后不能再向该站点分配新骑手，历史数据保留。是否停用？',
        icon: 'warning',
      });
    }
    const payload: SiteForm = {
      advance_limit: values.advance_limit,
      code: values.code,
      cycle_config:
        values.settle_cycle === 'custom'
          ? { anchor_day: values.anchor_day }
          : null,
      monthly_advance_limit: normalizeMonthlyAdvanceLimit(
        values.monthly_advance_limit,
      ),
      name: values.name,
      remark: values.remark,
      settle_cycle: values.settle_cycle,
      status: values.status,
    };
    drawerApi.lock();
    try {
      if (formData.value?.id) {
        await updateSiteApi(formData.value.id, payload);
      } else {
        await createSiteApi(payload);
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
    const data = drawerApi.getData<SiteResult>();
    formApi.resetForm();
    if (data?.id) {
      formData.value = { id: data.id };
      formApi.setValues({
        ...data,
        anchor_day: data.cycle_config?.anchor_day,
        monthly_advance_limit: normalizeMonthlyAdvanceLimit(
          data.monthly_advance_limit,
        ),
      });
    } else {
      formData.value = undefined;
      formApi.setValues({ monthly_advance_limit: 1 });
    }
  },
});

const [ManagerDrawerComp, managerDrawerApi] = useVbenDrawer({
  connectedComponent: ManagerDrawer,
});
</script>

<template>
  <PageContainer>
    <Grid>
      <template #toolbar-actions>
        <VbenButton
          v-access:code="'rs:site:add'"
          @click="() => drawerApi.setData(null).open()"
        >
          <MaterialSymbolsAdd class="size-5" />
          新增站点
        </VbenButton>
      </template>
      <template #advance_limit="{ row }">
        <MoneyText :value="row.advance_limit" />
      </template>
      <template #manager_count="{ row }">
        <ManagerCountCell :site-id="row.id" />
      </template>
    </Grid>
    <Drawer :title="drawerTitle">
      <Form />
    </Drawer>
    <ManagerDrawerComp />
    <a-empty
      v-if="false"
      description="暂无站点，请先创建站点"
    />
  </PageContainer>
</template>
