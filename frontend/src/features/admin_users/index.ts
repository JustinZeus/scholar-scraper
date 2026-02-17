import { apiRequest } from "@/lib/api/client";

export interface AdminUser {
  id: number;
  email: string;
  is_active: boolean;
  is_admin: boolean;
  created_at: string;
  updated_at: string;
}

interface UsersListData {
  users: AdminUser[];
}

export interface CreateAdminUserPayload {
  email: string;
  password: string;
  is_admin: boolean;
}

export async function listAdminUsers(): Promise<AdminUser[]> {
  const response = await apiRequest<UsersListData>("/admin/users", { method: "GET" });
  return response.data.users;
}

export async function createAdminUser(payload: CreateAdminUserPayload): Promise<AdminUser> {
  const response = await apiRequest<AdminUser>("/admin/users", {
    method: "POST",
    body: payload,
  });
  return response.data;
}

export async function setAdminUserActive(userId: number, isActive: boolean): Promise<AdminUser> {
  const response = await apiRequest<AdminUser>(`/admin/users/${userId}/active`, {
    method: "PATCH",
    body: { is_active: isActive },
  });
  return response.data;
}

export async function resetAdminUserPassword(userId: number, newPassword: string): Promise<{ message: string }> {
  const response = await apiRequest<{ message: string }>(`/admin/users/${userId}/reset-password`, {
    method: "POST",
    body: { new_password: newPassword },
  });
  return response.data;
}
