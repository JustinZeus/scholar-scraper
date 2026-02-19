import { defineStore } from "pinia";

import { ApiRequestError } from "@/lib/api/errors";
import { fetchCsrfBootstrap } from "@/lib/api/csrf";
import { fetchMe, loginSession, logoutSession, type SessionUser } from "@/lib/auth/session";
import { useRunStatusStore } from "@/stores/run_status";
import { useUiStore } from "@/stores/ui";
import { useUserSettingsStore } from "@/stores/user_settings";

export type AuthState = "unknown" | "authenticated" | "anonymous";

export const useAuthStore = defineStore("auth", {
  state: () => ({
    state: "unknown" as AuthState,
    csrfToken: null as string | null,
    user: null as SessionUser | null,
  }),
  getters: {
    isAuthenticated: (state) => state.state === "authenticated",
    isAdmin: (state) => Boolean(state.user?.is_admin),
  },
  actions: {
    async bootstrapSession(): Promise<void> {
      const ui = useUiStore();
      ui.clearGlobalError();

      try {
        const csrf = await fetchCsrfBootstrap();
        this.csrfToken = csrf.data.csrf_token;

        if (!csrf.data.authenticated) {
          this.state = "anonymous";
          this.user = null;
          return;
        }

        const me = await fetchMe();
        this.state = "authenticated";
        this.user = me.data.user;
        this.csrfToken = me.data.csrf_token;
      } catch (error) {
        this.state = "anonymous";
        this.user = null;

        if (error instanceof ApiRequestError) {
          ui.setGlobalError({
            message: error.message,
            requestId: error.requestId,
          });
        }
      }
    },
    async login(email: string, password: string): Promise<void> {
      const response = await loginSession({ email, password });
      this.state = "authenticated";
      this.user = response.data.user;
      this.csrfToken = response.data.csrf_token;
      const userSettings = useUserSettingsStore();
      const runStatus = useRunStatusStore();
      await userSettings.bootstrap();
      await runStatus.bootstrap();
    },
    async logout(): Promise<void> {
      await logoutSession();
      this.state = "anonymous";
      this.user = null;
      this.csrfToken = null;
      const userSettings = useUserSettingsStore();
      const runStatus = useRunStatusStore();
      userSettings.reset();
      runStatus.reset();

      try {
        const csrf = await fetchCsrfBootstrap();
        this.csrfToken = csrf.data.csrf_token;
      } catch (_err) {
        // No-op: app can still function by refreshing.
      }
    },
  },
});
