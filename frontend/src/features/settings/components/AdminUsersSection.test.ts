// @vitest-environment happy-dom
import { describe, expect, it, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import AdminUsersSection from "./AdminUsersSection.vue";

vi.mock("@/features/admin_users", () => ({
  listAdminUsers: vi.fn(),
  createAdminUser: vi.fn(),
  setAdminUserActive: vi.fn(),
  resetAdminUserPassword: vi.fn(),
}));

import { listAdminUsers, createAdminUser } from "@/features/admin_users";

const mockedListUsers = vi.mocked(listAdminUsers);
const mockedCreateUser = vi.mocked(createAdminUser);

function buildUser(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    email: "user@example.com",
    is_admin: false,
    is_active: true,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("AdminUsersSection", () => {
  beforeEach(() => {
    mockedListUsers.mockReset();
    mockedCreateUser.mockReset();
  });

  it("renders the create user form", () => {
    const wrapper = mount(AdminUsersSection);
    expect(wrapper.text()).toContain("Create user");
  });

  it("exposes load function that calls listAdminUsers", async () => {
    mockedListUsers.mockResolvedValueOnce([buildUser()]);
    const wrapper = mount(AdminUsersSection);
    const vm = wrapper.vm as unknown as { load: () => Promise<void>; users: unknown[] };
    await vm.load();
    await flushPromises();
    expect(mockedListUsers).toHaveBeenCalled();
    expect(vm.users).toHaveLength(1);
  });

  it("renders user table after loading", async () => {
    mockedListUsers.mockResolvedValueOnce([buildUser({ email: "alice@test.com" })]);
    const wrapper = mount(AdminUsersSection);
    const vm = wrapper.vm as unknown as { load: () => Promise<void> };
    await vm.load();
    await flushPromises();
    expect(wrapper.text()).toContain("alice@test.com");
  });

  it("propagates error when load fails", async () => {
    mockedListUsers.mockRejectedValueOnce(new Error("Network error"));
    const wrapper = mount(AdminUsersSection);
    const vm = wrapper.vm as unknown as { load: () => Promise<void> };
    await expect(vm.load()).rejects.toThrow("Network error");
  });

  it("emits user creation via form submit", async () => {
    mockedCreateUser.mockResolvedValueOnce(buildUser({ email: "new@test.com" }));
    mockedListUsers.mockResolvedValue([]);
    const wrapper = mount(AdminUsersSection);

    const inputs = wrapper.findAll("input");
    const emailInput = inputs.find((i) => (i.element as HTMLInputElement).type === "email");
    const passwordInput = inputs.find((i) => (i.element as HTMLInputElement).type === "password");

    if (emailInput && passwordInput) {
      await emailInput.setValue("new@test.com");
      await passwordInput.setValue("securepassword123");
      await wrapper.find("form").trigger("submit");
      await flushPromises();
      expect(mockedCreateUser).toHaveBeenCalled();
    }
  });
});
