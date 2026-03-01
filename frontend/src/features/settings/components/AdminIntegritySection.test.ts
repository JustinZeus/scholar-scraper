// @vitest-environment happy-dom
import { describe, expect, it, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import AdminIntegritySection from "./AdminIntegritySection.vue";

vi.mock("@/features/admin_dbops", () => ({
  getAdminDbIntegrityReport: vi.fn(),
}));

import { getAdminDbIntegrityReport, type AdminDbIntegrityReport } from "@/features/admin_dbops";

const mockedGetReport = vi.mocked(getAdminDbIntegrityReport);

function buildReport(overrides: Partial<AdminDbIntegrityReport> = {}): AdminDbIntegrityReport {
  return {
    status: "ok",
    warnings: [],
    failures: [],
    checked_at: "2025-01-15T12:00:00Z",
    checks: [
      { name: "orphaned_publications", count: 0, severity: "metric", message: "No orphaned publications found." },
    ],
    ...overrides,
  };
}

describe("AdminIntegritySection", () => {
  beforeEach(() => {
    mockedGetReport.mockReset();
  });

  it("renders the section heading", () => {
    const wrapper = mount(AdminIntegritySection);
    expect(wrapper.text()).toContain("Integrity Report");
  });

  it("exposes load function that fetches integrity report", async () => {
    mockedGetReport.mockResolvedValueOnce(buildReport());
    const wrapper = mount(AdminIntegritySection);
    const vm = wrapper.vm as unknown as { load: () => Promise<void> };
    await vm.load();
    await flushPromises();
    expect(mockedGetReport).toHaveBeenCalled();
  });

  it("renders check results after loading", async () => {
    mockedGetReport.mockResolvedValueOnce(buildReport());
    const wrapper = mount(AdminIntegritySection);
    const vm = wrapper.vm as unknown as { load: () => Promise<void> };
    await vm.load();
    await flushPromises();
    expect(wrapper.text()).toContain("orphaned_publications");
  });

  it("displays warning count when present", async () => {
    mockedGetReport.mockResolvedValueOnce(buildReport({ warnings: ["w1", "w2", "w3"] }));
    const wrapper = mount(AdminIntegritySection);
    const vm = wrapper.vm as unknown as { load: () => Promise<void> };
    await vm.load();
    await flushPromises();
    expect(wrapper.text()).toContain("3");
  });

  it("renders status badge", async () => {
    mockedGetReport.mockResolvedValueOnce(buildReport({ status: "failed" }));
    const wrapper = mount(AdminIntegritySection);
    const vm = wrapper.vm as unknown as { load: () => Promise<void> };
    await vm.load();
    await flushPromises();
    expect(wrapper.text()).toContain("failed");
  });
});
