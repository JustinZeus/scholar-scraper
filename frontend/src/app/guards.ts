import type { Router } from "vue-router";

import { useAuthStore } from "@/stores/auth";

export function applyRouteGuards(router: Router): void {
  router.beforeEach((to) => {
    const auth = useAuthStore();

    if (to.meta.requiresAuth && !auth.isAuthenticated) {
      return { name: "login" };
    }

    if (to.meta.requiresAdmin && !auth.isAdmin) {
      return { name: "dashboard" };
    }

    if (to.meta.guestOnly && auth.isAuthenticated) {
      return { name: "dashboard" };
    }

    return true;
  });
}
