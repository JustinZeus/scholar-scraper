import { apiRequest } from "@/lib/api/client";
import { type ScrapeSafetyState } from "@/features/safety";

export interface UserSettingsPolicy {
  min_run_interval_minutes: number;
  min_request_delay_seconds: number;
  automation_allowed: boolean;
  manual_run_allowed: boolean;
  blocked_failure_threshold: number;
  network_failure_threshold: number;
  cooldown_blocked_seconds: number;
  cooldown_network_seconds: number;
}

export interface UserSettings {
  auto_run_enabled: boolean;
  run_interval_minutes: number;
  request_delay_seconds: number;
  nav_visible_pages: string[];
  policy: UserSettingsPolicy;
  safety_state: ScrapeSafetyState;
}

export interface UserSettingsUpdate {
  auto_run_enabled: boolean;
  run_interval_minutes: number;
  request_delay_seconds: number;
  nav_visible_pages: string[];
}

export interface ChangePasswordPayload {
  current_password: string;
  new_password: string;
  confirm_password: string;
}

export async function fetchSettings(): Promise<UserSettings> {
  const response = await apiRequest<UserSettings>("/settings", { method: "GET" });
  return response.data;
}

export async function updateSettings(payload: UserSettingsUpdate): Promise<UserSettings> {
  const response = await apiRequest<UserSettings>("/settings", {
    method: "PUT",
    body: payload,
  });
  return response.data;
}

export async function changePassword(payload: ChangePasswordPayload): Promise<{ message: string }> {
  const response = await apiRequest<{ message: string }>("/auth/change-password", {
    method: "POST",
    body: payload,
  });
  return response.data;
}
