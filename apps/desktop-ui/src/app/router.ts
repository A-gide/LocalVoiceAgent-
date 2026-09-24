import { createRouter, createWebHashHistory } from 'vue-router';
import CharacterView from '@/features/character/CharacterView.vue';
import ChatView from '@/features/chat/ChatView.vue';
import MemoryView from '@/features/memory/MemoryView.vue';
import SettingsView from '@/features/settings/SettingsView.vue';
import ServicesView from '@/features/services/ServicesView.vue';

const routes = [
  {
    path: '/',
    name: 'character',
    component: CharacterView,
  },
  {
    path: '/character',
    redirect: '/',
  },
  {
    path: '/chat',
    name: 'chat',
    component: ChatView,
  },
  {
    path: '/memory',
    name: 'memory',
    component: MemoryView,
  },
  {
    path: '/settings',
    name: 'settings',
    component: SettingsView,
  },
  {
    path: '/services',
    name: 'services',
    component: ServicesView,
  },
];

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
});
