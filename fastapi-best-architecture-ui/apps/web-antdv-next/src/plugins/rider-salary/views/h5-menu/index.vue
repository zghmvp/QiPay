<script lang="ts" setup>
import type { H5Menu } from '../../types/h5-menu';
import type { SiteResult } from '../../types/site';

import { computed, reactive, ref } from 'vue';

import { useAccess } from '@vben/access';
import { useUserStore } from '@vben/stores';

import { message } from 'antdv-next';

import { getH5MenuApi, saveH5MenuApi } from '../../api/h5-menu';
import { getAllSitesApi } from '../../api/site';
import PageContainer from '../_shared/PageContainer.vue';

const userStore = useUserStore();
const { hasAccessByCodes } = useAccess();
const canSave = computed(() => {
  const info = userStore.userInfo as { is_superuser?: boolean } | null;
  return Boolean(info?.is_superuser) || hasAccessByCodes(['rs:h5:menu']);
});

const loading = ref(false);
const saving = ref(false);
const sites = ref<SiteResult[]>([]);
const source = ref<H5Menu['source']>('builtin');

const form = reactive({
  site_id: 0,
  show_home: true,
  show_adjustments: true,
  show_advance: true,
  show_notices: true,
  show_plan: true,
  show_home_pay: true,
  show_day_amount: true,
  show_estimate_net: true,
  show_advance_inflight: true,
});

const siteOptions = computed(() => [
  { label: '全局默认', value: 0 },
  ...sites.value.map((item) => ({
    label: `${item.name}（${item.code}）`,
    value: item.id,
  })),
]);

const sourceText = computed(() => {
  if (form.site_id === 0 && source.value === 'global') {
    return '这是已保存的全局开关，没有单独配置的站点都会沿用。';
  }
  if (form.site_id !== 0 && source.value === 'site') {
    return '这是该站点单独保存的开关。';
  }
  if (source.value === 'global') {
    return '该站点还没有单独保存，正在沿用全局开关。保存后只对该站点生效。';
  }
  return '还没有保存过开关，下面是全部开放。保存后开始生效。';
});

const groups = [
  {
    title: '底部入口',
    rows: [
      { key: 'show_home', label: '首页', hint: '底部「首页」。关闭后登录进入「我的」' },
      { key: 'show_adjustments', label: '奖惩', hint: '底部「奖惩」' },
      { key: 'show_advance', label: '预支', hint: '底部「预支」，关闭后不能申请' },
      { key: 'show_notices', label: '公告', hint: '底部「公告」' },
    ],
  },
  {
    title: '首页内容',
    rows: [
      { key: 'show_plan', label: '当前方案', hint: '首页上的方案入口' },
      {
        key: 'show_home_pay',
        label: '首页工资',
        hint: '本期预计工资、应发、代扣和预支抵扣。单量仍显示',
      },
      {
        key: 'show_day_amount',
        label: '当日金额',
        hint: '当日净额、订单金额、奖惩金额，以及月历上的奖惩圆点。格子仍显示单量',
      },
    ],
  },
  {
    title: '预支数字',
    rows: [
      { key: 'show_estimate_net', label: '预估实发', hint: '预支页上的预估实发' },
      { key: 'show_advance_inflight', label: '在途占用', hint: '预支页上的在途占用' },
    ],
  },
] as const;

function apply(data: H5Menu) {
  source.value = data.source;
  form.show_home = data.show_home;
  form.show_adjustments = data.show_adjustments;
  form.show_advance = data.show_advance;
  form.show_notices = data.show_notices;
  form.show_plan = data.show_plan;
  form.show_home_pay = data.show_home_pay;
  form.show_day_amount = data.show_day_amount;
  form.show_estimate_net = data.show_estimate_net;
  form.show_advance_inflight = data.show_advance_inflight;
}

async function load(fallback = true) {
  loading.value = true;
  try {
    apply(await getH5MenuApi(form.site_id));
  } catch (error) {
    if (fallback && form.site_id === 0 && sites.value[0]) {
      form.site_id = sites.value[0].id;
      loading.value = false;
      await load(false);
      return;
    }
    throw error;
  } finally {
    loading.value = false;
  }
}

async function onSave() {
  saving.value = true;
  try {
    const saved = await saveH5MenuApi({
      site_id: form.site_id,
      show_home: form.show_home,
      show_adjustments: form.show_adjustments,
      show_advance: form.show_advance,
      show_notices: form.show_notices,
      show_plan: form.show_plan,
      show_home_pay: form.show_home_pay,
      show_day_amount: form.show_day_amount,
      show_estimate_net: form.show_estimate_net,
      show_advance_inflight: form.show_advance_inflight,
    });
    source.value = saved.source;
    message.success('骑手端菜单已保存');
  } finally {
    saving.value = false;
  }
}

sites.value = [];
void (async () => {
  sites.value = await getAllSitesApi();
  await load();
})();
</script>

<template>
  <PageContainer>
    <div class="menu-page">
      <a-spin :spinning="loading">
        <a-alert class="note" type="info" show-icon :message="sourceText" />
        <a-form layout="vertical">
          <a-form-item label="适用范围">
            <a-select v-model:value="form.site_id" :options="siteOptions" @change="load" />
          </a-form-item>
        </a-form>
        <section v-for="group in groups" :key="group.title" class="group">
          <h2>{{ group.title }}</h2>
          <div class="rows">
            <div v-for="row in group.rows" :key="row.key" class="row">
              <div>
                <div class="label">{{ row.label }}</div>
                <div class="hint">{{ row.hint }}</div>
              </div>
              <a-switch
                v-model:checked="form[row.key]"
                :disabled="group.title === '预支数字' && !form.show_advance"
                checked-children="开放"
                un-checked-children="关闭"
              />
            </div>
          </div>
        </section>
        <p class="hint foot">我的始终开放。首页关闭后，登录和直接打开地址会进入我的，月历和当日明细一并关闭。</p>
        <a-button
          v-if="canSave"
          type="primary"
          :auto-insert-space="false"
          :loading="saving"
          @click="onSave"
        >
          保存
        </a-button>
      </a-spin>
    </div>
  </PageContainer>
</template>

<style scoped>
.menu-page {
  max-width: 640px;
  padding: 16px;
}

.note {
  margin-bottom: 16px;
}

.group {
  margin-bottom: 8px;
}

.group h2 {
  margin: 8px 0 12px;
  font-size: 14px;
  font-weight: 600;
  line-height: 22px;
}

.rows {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 12px;
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
  border: 1px solid var(--ant-color-border-secondary, #f0f0f0);
  border-radius: 8px;
}

.label {
  font-size: 14px;
  line-height: 22px;
}

.hint {
  color: var(--ant-color-text-secondary, rgb(0 0 0 / 45%));
  font-size: 12px;
  line-height: 20px;
}

.foot {
  margin: 0 0 16px;
}
</style>
