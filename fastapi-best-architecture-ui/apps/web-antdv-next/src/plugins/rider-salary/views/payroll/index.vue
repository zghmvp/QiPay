<script lang="ts" setup>
import type { VbenFormProps } from '@vben/common-ui';

import type { PayrollSummary } from '../../types/payroll';

import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';

import { onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { useVbenVxeGrid } from '#/adapter/vxe-table';

import { getPeriodApi } from '../../api/period';
import { getPayrollListApi } from '../../api/payroll';
import MoneyText from '../../components/MoneyText.vue';
import PageContainer from '../_shared/PageContainer.vue';
import { querySchema, useColumns } from './data';

const route = useRoute();
const router = useRouter();

function queryStr(key: string) {
  const raw = route.query[key];
  const v = Array.isArray(raw) ? raw[0] : raw;
  return typeof v === 'string' && v ? v : undefined;
}

function queryNum(key: string) {
  const n = Number(queryStr(key));
  return Number.isFinite(n) && n > 0 ? n : undefined;
}

function queryBool(key: string) {
  const v = queryStr(key);
  if (v === 'true' || v === '1') return true;
  if (v === 'false' || v === '0') return false;
  return undefined;
}

const initialSiteId = queryNum('site_id');
const initialPeriodId = queryNum('period_id');
const initialRiderId = queryNum('rider_id');
const initialStatus = queryStr('status');
const initialKind = queryStr('kind');
const initialStale = queryBool('stale');

const formOptions: VbenFormProps = {
  collapsed: true,
  schema: querySchema.map((item) => {
    if (item.fieldName === 'site_id' && initialSiteId) {
      return { ...item, defaultValue: initialSiteId };
    }
    if (item.fieldName === 'period_id' && initialPeriodId) {
      return { ...item, defaultValue: initialPeriodId };
    }
    if (item.fieldName === 'rider_id' && initialRiderId) {
      return { ...item, defaultValue: initialRiderId };
    }
    if (item.fieldName === 'status' && initialStatus) {
      return { ...item, defaultValue: initialStatus };
    }
    if (item.fieldName === 'kind' && initialKind) {
      return { ...item, defaultValue: initialKind };
    }
    if (item.fieldName === 'stale' && initialStale !== undefined) {
      return { ...item, defaultValue: initialStale };
    }
    return item;
  }),
  showCollapseButton: true,
  submitButtonOptions: { content: '查询' },
};

function openDetail(row: PayrollSummary) {
  router.push({ path: `/rider-salary/payroll/${row.id}` });
}

function onActionClick({ code, row }: OnActionClickParams<PayrollSummary>) {
  if (code === 'detail') openDetail(row);
}

const gridOptions: VxeTableGridOptions<PayrollSummary> = {
  columns: useColumns(onActionClick),
  emptyText: '暂无薪资结果',
  height: 'auto',
  proxyConfig: {
    ajax: {
      query: async ({ page }, formValues) => {
        return await getPayrollListApi({
          page: page.currentPage,
          size: page.pageSize,
          ...(formValues as Record<string, unknown>),
        });
      },
    },
  },
  rowConfig: { isHover: true, keyField: 'id' },
  toolbarConfig: {
    custom: true,
    refresh: true,
    refreshOptions: { code: 'query' },
  },
};

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions,
  gridOptions,
  gridEvents: {
    cellClick: ({ row }: { row: PayrollSummary }) => {
      openDetail(row);
    },
  },
});

onMounted(async () => {
  let siteId = initialSiteId;
  let periodId = initialPeriodId;
  if (periodId && !siteId) {
    try {
      const period = await getPeriodApi(periodId);
      siteId = period.site_id;
    } catch {
      periodId = undefined;
    }
  }
  const values: Record<string, unknown> = {};
  if (siteId) values.site_id = siteId;
  if (periodId) values.period_id = periodId;
  if (initialRiderId) values.rider_id = initialRiderId;
  if (initialStatus) values.status = initialStatus;
  if (initialKind) values.kind = initialKind;
  if (initialStale !== undefined) values.stale = initialStale;
  if (Object.keys(values).length) {
    await gridApi.formApi.setValues(values);
  }
});
</script>

<template>
  <PageContainer>
    <Grid data-testid="payroll-list-grid" table-title="薪资结果">
      <template #gross="{ row }">
        <MoneyText :value="row.gross" />
      </template>
      <template #net="{ row }">
        <MoneyText :value="row.net" />
      </template>
    </Grid>
  </PageContainer>
</template>
