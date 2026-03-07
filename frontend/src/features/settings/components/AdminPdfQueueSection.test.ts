// @vitest-environment happy-dom
import { describe, expect, it, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import { setActivePinia, createPinia } from "pinia";
import { useAuthStore } from "@/stores/auth";
import AdminPdfQueueSection from "./AdminPdfQueueSection.vue";

vi.mock("@/features/admin_dbops", () => ({
  listAdminPdfQueue: vi.fn(),
  requeueAdminPdfLookup: vi.fn(),
  requeueAllAdminPdfLookups: vi.fn(),
}));

import { listAdminPdfQueue } from "@/features/admin_dbops";

const mockedListQueue = vi.mocked(listAdminPdfQueue);

function buildQueueItem(overrides: Record<string, unknown> = {}) {
  return {
    publication_id: 1,
    title: "Test Paper",
    display_identifier: null,
    pdf_url: null,
    status: "queued",
    attempt_count: 0,
    last_failure_reason: null,
    last_failure_detail: null,
    last_source: "unpaywall",
    requested_by_user_id: null,
    requested_by_email: null,
    queued_at: "2025-01-15T12:00:00Z",
    last_attempt_at: null,
    resolved_at: null,
    updated_at: "2025-01-15T12:00:00Z",
    ...overrides,
  };
}

describe("AdminPdfQueueSection", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    const auth = useAuthStore();
    auth.$patch({ state: "authenticated", user: { id: 1, email: "admin@test.com", is_admin: true, is_active: true } });
    mockedListQueue.mockReset();
  });

  it("renders the PDF queue heading", () => {
    const wrapper = mount(AdminPdfQueueSection);
    expect(wrapper.text()).toContain("PDF");
  });

  it("exposes load function that fetches PDF queue", async () => {
    mockedListQueue.mockResolvedValueOnce({
      items: [buildQueueItem()],
      total_count: 1,
      has_next: false,
      has_prev: false,
      page: 1,
      page_size: 50,
    });
    const wrapper = mount(AdminPdfQueueSection);
    const vm = wrapper.vm as unknown as { load: () => Promise<void> };
    await vm.load();
    await flushPromises();
    expect(mockedListQueue).toHaveBeenCalled();
  });

  it("renders queue items after loading", async () => {
    mockedListQueue.mockResolvedValueOnce({
      items: [buildQueueItem({ title: "My Paper" })],
      total_count: 1,
      has_next: false,
      has_prev: false,
      page: 1,
      page_size: 50,
    });
    const wrapper = mount(AdminPdfQueueSection);
    const vm = wrapper.vm as unknown as { load: () => Promise<void> };
    await vm.load();
    await flushPromises();
    expect(wrapper.text()).toContain("My Paper");
  });

  it("renders status filter dropdown", () => {
    const wrapper = mount(AdminPdfQueueSection);
    expect(wrapper.text()).toContain("Status");
  });

  it("renders queue all button", () => {
    const wrapper = mount(AdminPdfQueueSection);
    expect(wrapper.text()).toContain("Queue all");
  });

  it("shows pagination summary after loading", async () => {
    mockedListQueue.mockResolvedValueOnce({
      items: Array.from({ length: 3 }, (_, i) => buildQueueItem({ publication_id: i + 1 })),
      total_count: 3,
      has_next: false,
      has_prev: false,
      page: 1,
      page_size: 50,
    });
    const wrapper = mount(AdminPdfQueueSection);
    const vm = wrapper.vm as unknown as { load: () => Promise<void> };
    await vm.load();
    await flushPromises();
    expect(wrapper.text()).toContain("3");
  });
});
