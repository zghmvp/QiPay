<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Cell, Empty, NavBar, Tag } from 'vant'
import { getPlan } from '@/api/me'
import { BINDING_TYPE_OPTIONS, enumLabel, PLAN_MODE_TAG_OPTIONS } from '@/constants/enums'
import type { MePlan } from '@/types'

const router = useRouter()
const loading = ref(true)
const data = ref<MePlan | null>(null)
const bindings = computed(() => data.value?.bindings || [])

onMounted(async () => {
  try {
    data.value = await getPlan()
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div>
    <NavBar title="当前方案" left-arrow @click-left="router.back()" />
    <div class="page-body no-tab">
      <Empty v-if="!loading && !bindings.length" description="当前没有生效的薪资方案，请联系站点" />
      <article v-for="item in bindings" :key="item.plan_version_id + item.start_date" class="card-block plan">
        <header>
          <h2>{{ item.plan_name }}</h2>
          <Tag :color="item.color || '#ff7a1a'" text-color="#fff" round>{{ item.short_name }}</Tag>
        </header>
        <p class="muted">
          版本 v{{ item.version_no }}
          ·
          {{ enumLabel(PLAN_MODE_TAG_OPTIONS, item.mode_tag) }}
          ·
          {{ enumLabel(BINDING_TYPE_OPTIONS, item.binding_type) }}
          <Tag v-if="item.is_current" size="mini" type="success">当前生效</Tag>
        </p>
        <p>
          生效区间 {{ item.start_date }} ~ {{ item.end_date || '长期' }}
        </p>
        <Cell
          v-for="(row, idx) in item.items"
          :key="idx"
          :title="row.name"
          :value="row.subject_name"
        />
      </article>
    </div>
  </div>
</template>

<style scoped>
.plan {
  padding: 14px 8px 8px;
  margin-bottom: 12px;
}

.plan header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 8px;
}

.plan h2 {
  margin: 0;
  font-size: 16px;
}

.plan p {
  margin: 6px 8px;
}
</style>
