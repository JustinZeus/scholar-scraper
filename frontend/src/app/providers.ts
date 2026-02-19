import { setCsrfTokenProvider } from "@/lib/api/client";
import { useAuthStore } from "@/stores/auth";
import { useThemeStore } from "@/stores/theme";
import { useUserSettingsStore } from "@/stores/user_settings";

export async function bootstrapAppProviders(): Promise<void> {
  const theme = useThemeStore();
  theme.initialize();

  const auth = useAuthStore();
  setCsrfTokenProvider(() => auth.csrfToken);
  await auth.bootstrapSession();

  const userSettings = useUserSettingsStore();
  if (auth.isAuthenticated) {
    await userSettings.bootstrap();
  } else {
    userSettings.reset();
  }
}
