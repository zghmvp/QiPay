<script lang="ts" setup>
import type { PageResult } from '../../../types/common';
import type { SiteManagerItem, SiteManagerResult } from '../../../types/site';

import { computed, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { message } from 'antdv-next';

import { getSysUserListApi } from '#/api';
import { requestClient } from '#/api/request';

import { getSiteManagersApi, updateSiteManagersApi } from '../../../api/site';
import { MANAGER_ROLE_OPTIONS } from '../../../constants/enums';

interface SysUserItem {
  id: number;
  nickname: string;
  username: string;
}

interface AssignedRow {
  nickname: string;
  role: 'deputy' | 'owner';
  user_id: number;
  username: string;
}

const keyword = ref('');
const loadingUsers = ref(false);
const loadingManagers = ref(false);
const saving = ref(false);
const users = ref<SysUserItem[]>([]);
const assigned = ref<AssignedRow[]>([]);

const siteId = computed(
  () => drawerApi.getData<{ id?: number; onSuccess?: () => void }>()?.id,
);

const [Drawer, drawerApi] = useVbenDrawer({
  class: 'w-[820px]',
  confirmText: '保存负责人',
  destroyOnClose: true,
  async onConfirm() {
    const owners = assigned.value.filter((item) => item.role === 'owner');
    if (owners.length > 1) {
      message.warning('负责人最多 1 人');
      return;
    }
    const pk = siteId.value;
    if (!pk) return;
    saving.value = true;
    drawerApi.lock();
    try {
      const payload: SiteManagerItem[] = assigned.value.map((item) => ({
        role: item.role,
        user_id: item.user_id,
      }));
      await updateSiteManagersApi(pk, payload);
      message.success('已保存负责人');
      drawerApi.getData<{ id?: number; onSuccess?: () => void }>()?.onSuccess?.();
      await drawerApi.close();
    } finally {
      saving.value = false;
      drawerApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) return;
    keyword.value = '';
    assigned.value = [];
    users.value = [];
    await Promise.all([loadUsers(), loadManagers()]);
  },
});

async function loadUsers() {
  loadingUsers.value = true;
  try {
    const res = (await getSysUserListApi({
      page: 1,
      size: 50,
      username: keyword.value || undefined,
    })) as unknown as PageResult<SysUserItem>;
    users.value = res?.items ?? [];
  } catch {
    try {
      const res = await requestClient.get<PageResult<SysUserItem>>(
        '/api/v1/sys/users',
        {
          params: {
            page: 1,
            size: 50,
            username: keyword.value || undefined,
          },
        },
      );
      users.value = res?.items ?? [];
    } catch {
      users.value = [];
    }
  } finally {
    loadingUsers.value = false;
  }
}

async function loadManagers() {
  const pk = siteId.value;
  if (!pk) return;
  loadingManagers.value = true;
  try {
    const list = (await getSiteManagersApi(pk)) ?? [];
    assigned.value = list.map((item: SiteManagerResult) => ({
      nickname: item.nickname,
      role: item.role === 'owner' ? 'owner' : 'deputy',
      user_id: item.user_id,
      username: item.username,
    }));
  } catch {
    assigned.value = [];
  } finally {
    loadingManagers.value = false;
  }
}

function isAssigned(userId: number) {
  return assigned.value.some((item) => item.user_id === userId);
}

function addUser(user: SysUserItem) {
  if (isAssigned(user.id)) return;
  const hasOwner = assigned.value.some((item) => item.role === 'owner');
  assigned.value.push({
    nickname: user.nickname,
    role: hasOwner ? 'deputy' : 'owner',
    user_id: user.id,
    username: user.username,
  });
}

function removeUser(userId: number) {
  assigned.value = assigned.value.filter((item) => item.user_id !== userId);
}

function onRoleChange(userId: number, role: 'deputy' | 'owner') {
  if (role === 'owner') {
    assigned.value = assigned.value.map((item) =>
      item.user_id === userId
        ? { ...item, role: 'owner' }
        : { ...item, role: item.role === 'owner' ? 'deputy' : item.role },
    );
    return;
  }
  assigned.value = assigned.value.map((item) =>
    item.user_id === userId ? { ...item, role } : item,
  );
}
</script>

<template>
  <Drawer title="配置站点负责人">
    <div class="grid grid-cols-2 gap-4">
      <div>
        <div class="mb-2 font-medium">系统用户</div>
        <a-input-search
          v-model:value="keyword"
          allow-clear
          class="mb-2"
          placeholder="搜索用户名"
          @search="loadUsers"
        />
        <a-spin :spinning="loadingUsers">
          <a-empty v-if="users.length === 0" description="没有符合条件的用户" />
          <a-list v-else size="small" :data-source="users">
            <template #renderItem="{ item }">
              <a-list-item>
                <a-list-item-meta
                  :title="item.nickname || item.username"
                  :description="item.username"
                />
                <template #actions>
                  <a-button
                    size="small"
                    type="link"
                    :disabled="isAssigned(item.id)"
                    @click="addUser(item)"
                  >
                    {{ isAssigned(item.id) ? '已添加' : '添加' }}
                  </a-button>
                </template>
              </a-list-item>
            </template>
          </a-list>
        </a-spin>
      </div>
      <div>
        <div class="mb-2 font-medium">已选负责人（owner 最多 1 人）</div>
        <a-spin :spinning="loadingManagers || saving">
          <a-empty v-if="assigned.length === 0" description="尚未配置负责人" />
          <a-list v-else size="small" :data-source="assigned">
            <template #renderItem="{ item }">
              <a-list-item>
                <a-list-item-meta
                  :title="item.nickname || item.username"
                  :description="item.username"
                />
                <template #actions>
                  <a-select
                    :value="item.role"
                    :options="MANAGER_ROLE_OPTIONS"
                    size="small"
                    class="w-[110px]"
                    @update:value="(val) => onRoleChange(item.user_id, val === 'owner' ? 'owner' : 'deputy')"
                  />
                  <a-button
                    size="small"
                    type="link"
                    danger
                    @click="removeUser(item.user_id)"
                  >
                    移除
                  </a-button>
                </template>
              </a-list-item>
            </template>
          </a-list>
        </a-spin>
      </div>
    </div>
  </Drawer>
</template>
