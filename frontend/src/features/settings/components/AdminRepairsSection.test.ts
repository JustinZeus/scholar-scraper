// @vitest-environment happy-dom
import { describe, expect, it, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import AdminRepairsSection from "./AdminRepairsSection.vue";

vi.mock("@/features/admin_dbops", () => ({
  listAdminDbRepairJobs: vi.fn(),
  triggerPublicationLinkRepair: vi.fn(),
  triggerPublicationNearDuplicateRepair: vi.fn(),
  dropAllPublications: vi.fn(),
}));

import { listAdminDbRepairJobs, dropAllPublications } from "@/features/admin_dbops";

const mockedListJobs = vi.mocked(listAdminDbRepairJobs);
const mockedDrop = vi.mocked(dropAllPublications);

function buildUser(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    email: "admin@test.com",
    is_admin: true,
    is_active: true,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("AdminRepairsSection", () => {
  beforeEach(() => {
    mockedListJobs.mockReset();
    mockedDrop.mockReset();
  });

  it("renders the repair sections", () => {
    const wrapper = mount(AdminRepairsSection, { props: { users: [buildUser()] } });
    expect(wrapper.text()).toContain("Publication Link Repair");
    expect(wrapper.text()).toContain("Near-Duplicate");
    expect(wrapper.text()).toContain("Drop All Publications");
  });

  it("exposes load function that fetches repair jobs", async () => {
    mockedListJobs.mockResolvedValueOnce([]);
    const wrapper = mount(AdminRepairsSection, { props: { users: [buildUser()] } });
    const vm = wrapper.vm as unknown as { load: () => Promise<void> };
    await vm.load();
    await flushPromises();
    expect(mockedListJobs).toHaveBeenCalled();
  });

  it("renders repair job rows after loading", async () => {
    mockedListJobs.mockResolvedValueOnce([
      {
        id: 1,
        job_name: "publication_link_repair",
        status: "completed",
        dry_run: true,
        requested_by: "admin@test.com",
        scope: {},
        summary: { links_in_scope: 100, links_deleted: 5 },
        error_text: null,
        started_at: "2025-01-15T12:00:00Z",
        finished_at: "2025-01-15T12:01:00Z",
        created_at: "2025-01-15T12:00:00Z",
        updated_at: "2025-01-15T12:01:00Z",
      },
    ]);
    const wrapper = mount(AdminRepairsSection, { props: { users: [buildUser()] } });
    const vm = wrapper.vm as unknown as { load: () => Promise<void> };
    await vm.load();
    await flushPromises();
    expect(wrapper.text()).toContain("publication_link_repair");
  });

  it("has typed confirmation guard for drop all publications", () => {
    const wrapper = mount(AdminRepairsSection, { props: { users: [buildUser()] } });
    const dropButton = wrapper.findAll("button").find((b) => b.text().includes("Drop all publications"));
    expect(dropButton?.attributes("disabled")).toBeDefined();
  });

  it("renders dry-run toggle in repair form", () => {
    const wrapper = mount(AdminRepairsSection, { props: { users: [buildUser()] } });
    expect(wrapper.text()).toContain("Dry-run");
  });

  it("renders scope mode selector", () => {
    const wrapper = mount(AdminRepairsSection, { props: { users: [buildUser()] } });
    expect(wrapper.text()).toContain("Scope");
  });
});
