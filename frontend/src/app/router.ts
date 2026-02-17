import { createRouter, createWebHistory } from "vue-router";

import { applyRouteGuards } from "@/app/guards";
import LoginPage from "@/pages/LoginPage.vue";
import DashboardPage from "@/pages/DashboardPage.vue";
import ScholarsPage from "@/pages/ScholarsPage.vue";
import PublicationsPage from "@/pages/PublicationsPage.vue";
import RunsPage from "@/pages/RunsPage.vue";
import RunDetailPage from "@/pages/RunDetailPage.vue";
import SettingsPage from "@/pages/SettingsPage.vue";
import AdminUsersPage from "@/pages/AdminUsersPage.vue";
import StyleGuidePage from "@/pages/StyleGuidePage.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/login",
      name: "login",
      component: LoginPage,
      meta: { guestOnly: true },
    },
    {
      path: "/",
      redirect: "/dashboard",
    },
    {
      path: "/dashboard",
      name: "dashboard",
      component: DashboardPage,
      meta: { requiresAuth: true },
    },
    {
      path: "/scholars",
      name: "scholars",
      component: ScholarsPage,
      meta: { requiresAuth: true },
    },
    {
      path: "/publications",
      name: "publications",
      component: PublicationsPage,
      meta: { requiresAuth: true },
    },
    {
      path: "/settings",
      name: "settings",
      component: SettingsPage,
      meta: { requiresAuth: true },
    },
    {
      path: "/admin/style-guide",
      name: "style-guide",
      component: StyleGuidePage,
      meta: { requiresAuth: true, requiresAdmin: true },
    },
    {
      path: "/admin/runs",
      name: "runs",
      component: RunsPage,
      meta: { requiresAuth: true, requiresAdmin: true },
    },
    {
      path: "/admin/runs/:id",
      name: "run-detail",
      component: RunDetailPage,
      meta: { requiresAuth: true, requiresAdmin: true },
    },
    {
      path: "/admin/users",
      name: "admin-users",
      component: AdminUsersPage,
      meta: { requiresAuth: true, requiresAdmin: true },
    },
    {
      path: "/:pathMatch(.*)*",
      redirect: "/dashboard",
    },
  ],
});

applyRouteGuards(router);

export default router;
