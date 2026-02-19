import { setCsrfTokenProvider } from "@/lib/api/client";
import { useAuthStore } from "@/stores/auth";
import { useRunStatusStore } from "@/stores/run_status";
import { useThemeStore } from "@/stores/theme";
import { useUserSettingsStore } from "@/stores/user_settings";

export async function bootstrapAppProviders(): Promise<void> {
  const theme = useThemeStore();
  theme.initialize();

  const auth = useAuthStore();
  setCsrfTokenProvider(() => auth.csrfToken);
  await auth.bootstrapSession();

  const userSettings = useUserSettingsStore();
  const runStatus = useRunStatusStore();
  if (auth.isAuthenticated) {
    await userSettings.bootstrap();
    await runStatus.bootstrap();
  } else {
    userSettings.reset();
    runStatus.reset();
  }
}
