import { apiRequest } from "@/lib/api/client";

export interface UserSettings {
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

export async function updateSettings(payload: UserSettings): Promise<UserSettings> {
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
