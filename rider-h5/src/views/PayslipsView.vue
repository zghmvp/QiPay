<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Empty, NavBar, Skeleton } from 'vant'
import MoneyText from '@/components/MoneyText.vue'
import { getPayslips, getProfile } from '@/api/me'
import { useAuthStore } from '@/stores/auth'
import type { MePayslipItem } from '@/types'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(true)
const failed = ref(false)
const list = ref<MePayslipItem[]>([])

async function load() {
  loading.value = true
  failed.value = false
  try {
    const [rows, profile] = await Promise.all([getPayslips(), getProfile()])
    list.value = rows
    auth.profile = profile
  } catch {
    list.value = []
    failed.value = true
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div>
    <NavBar title="往期工资" left-arrow @click-left="router.back()" />
    <div class="page-body no-tab">
      <p v-if="auth.profile?.read_only" class="muted grace">
        已离职，只读查阅至 {{ auth.profile.read_until || '宽限期结束' }}，不能提交预支
      </p>
      <Skeleton :loading="loading" title :row="4">
        <Empty v-if="failed" description="工资条加载失败，请重试">
          <button type="button" class="retry" @click="load">重试</button>
        </Empty>
        <Empty v-else-if="!list.length" description="暂无已定稿的工资条" />
        <button
          v-for="item in list"
          :key="item.id"
          type="button"
          class="card-block slip"
          @click="router.push(`/payslips/${item.id}`)"
        >
          <p class="waybill-kicker">{{ item.period_range }}</p>
          <p class="waybill-amount display-num"><MoneyText :value="item.net" /></p>
          <p class="muted">
            {{ item.status_label }} · {{ item.kind_label }} · {{ item.period_status_label }}
          </p>
          <p class="muted">单量 {{ item.order_count }}</p>
        </button>
      </Skeleton>
    </div>
  </div>
</template>

<style scoped>
.grace {
  margin: 0 2px 12px;
}

.slip {
  display: block;
  width: 100%;
  text-align: left;
  padding: 14px;
  margin-bottom: 10px;
  border: 1px solid var(--line);
  background: var(--paper-2);
}

.slip p {
  margin: 4px 0;
}

.retry {
  margin-top: 8px;
  border: 0;
  background: var(--vis);
  color: #fff;
  border-radius: 999px;
  padding: 6px 14px;
}
</style>
