// @vitest-environment happy-dom
import { describe, expect, it, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import { nextTick } from "vue";
import SettingsAdminPanel from "./SettingsAdminPanel.vue";

vi.mock("@/features/admin_users", () => ({
  listAdminUsers: vi.fn().mockResolvedValue([]),
  createAdminUser: vi.fn(),
  setAdminUserActive: vi.fn(),
  resetAdminUserPassword: vi.fn(),
}));

vi.mock("@/features/admin_dbops", () => ({
  getAdminDbIntegrityReport: vi.fn().mockResolvedValue({
    status: "ok",
    warnings: [],
    failures: [],
    checked_at: null,
    checks: [],
  }),
  listAdminPdfQueue: vi.fn().mockResolvedValue({
    items: [],
    total_count: 0,
    has_next: false,
    has_prev: false,
    page: 1,
    page_size: 50,
  }),
  requeueAdminPdfLookup: vi.fn(),
  requeueAllAdminPdfLookups: vi.fn(),
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({ isAdmin: true }),
}));

vi.mock("@/features/admin_repairs", () => ({
  listAdminRepairTasks: vi.fn().mockResolvedValue([]),
  runAdminRepairTask: vi.fn(),
}));

import { listAdminUsers } from "@/features/admin_users";
import { getAdminDbIntegrityReport, listAdminPdfQueue } from "@/features/admin_dbops";

const mockedListUsers = vi.mocked(listAdminUsers);
const mockedGetReport = vi.mocked(getAdminDbIntegrityReport);
const mockedListPdfQueue = vi.mocked(listAdminPdfQueue);

describe("SettingsAdminPanel", () => {
  beforeEach(() => {
    mockedListUsers.mockClear();
    mockedGetReport.mockClear();
    mockedListPdfQueue.mockClear();
  });

  it("calls load on users section after nextTick when section=users", async () => {
    mount(SettingsAdminPanel, { props: { section: "users" } });
    await nextTick();
    await nextTick();
    await flushPromises();
    expect(mockedListUsers).toHaveBeenCalled();
  });

  it("calls load on integrity section after nextTick when section=integrity", async () => {
    mount(SettingsAdminPanel, { props: { section: "integrity" } });
    await nextTick();
    await nextTick();
    await flushPromises();
    expect(mockedGetReport).toHaveBeenCalled();
  });

  it("calls load on new section when section prop changes", async () => {
    const wrapper = mount(SettingsAdminPanel, { props: { section: "users" } });
    await nextTick();
    await nextTick();
    await flushPromises();
    mockedListUsers.mockClear();
    mockedGetReport.mockClear();

    await wrapper.setProps({ section: "integrity" });
    await nextTick();
    await flushPromises();
    expect(mockedGetReport).toHaveBeenCalled();
  });

  it("calls load on pdf section when section=pdf", async () => {
    mount(SettingsAdminPanel, { props: { section: "pdf" } });
    await nextTick();
    await nextTick();
    await flushPromises();
    expect(mockedListPdfQueue).toHaveBeenCalled();
  });
});
