<script lang="ts" setup>
import type { VbenFormProps } from '@vben/common-ui';

import type { AuditLogResult } from '../../types/audit';

import type { VxeTableGridOptions } from '#/adapter/vxe-table';

import { useVbenVxeGrid } from '#/adapter/vxe-table';

import { getAuditLogListApi } from '../../api/audit';
import PageContainer from '../_shared/PageContainer.vue';
import { querySchema, useColumns } from './data';

const formOptions: VbenFormProps = {
  collapsed: true,
  schema: querySchema,
  showCollapseButton: true,
  submitButtonOptions: { content: '查询' },
};

const gridOptions: VxeTableGridOptions<AuditLogResult> = {
  columns: useColumns(),
  expandConfig: { accordion: true },
  height: 'auto',
  proxyConfig: {
    ajax: {
      query: async ({ page }, formValues) => {
        const { date_range, ...rest } = formValues as {
          date_range?: [string, string];
        };
        return await getAuditLogListApi({
          date_from: date_range?.[0],
          date_to: date_range?.[1],
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

const [Grid] = useVbenVxeGrid({ formOptions, gridOptions });

function pretty(value: null | Record<string, unknown> | undefined) {
  if (!value) return '（无）';
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}
</script>

<template>
  <PageContainer>
    <Grid>
      <template #expandContent="{ row }">
        <div class="p-3">
          <div v-if="row.reason" class="mb-2 text-sm">
            原因：{{ row.reason }}
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <div class="mb-1 text-xs font-medium">变更前</div>
              <pre class="bg-muted max-h-64 overflow-auto rounded p-2 text-xs">{{
                pretty(row.before)
              }}</pre>
            </div>
            <div>
              <div class="mb-1 text-xs font-medium">变更后</div>
              <pre class="bg-muted max-h-64 overflow-auto rounded p-2 text-xs">{{
                pretty(row.after)
              }}</pre>
            </div>
          </div>
        </div>
      </template>
    </Grid>
  </PageContainer>
</template>
