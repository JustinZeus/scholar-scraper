// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import PublicationTableRow from "./PublicationTableRow.vue";
import type { PublicationItem } from "@/features/publications";

function buildItem(overrides: Partial<PublicationItem> = {}): PublicationItem {
  return {
    publication_id: 1,
    scholar_profile_id: 10,
    title: "Test Publication",
    year: 2025,
    citation_count: 42,
    pub_url: "https://example.com/pub",
    pdf_url: null,
    pdf_status: null,
    is_read: false,
    is_favorite: false,
    is_new_in_latest_run: true,
    scholar_label: "Dr. Test",
    first_seen_at: "2025-01-15T00:00:00Z",
    display_identifier: null,
    ...overrides,
  } as PublicationItem;
}

const defaultProps = {
  item: buildItem(),
  itemKey: "pub-1",
  selected: false,
  favoriteUpdating: false,
  retrying: false,
  canRetry: false,
};

describe("PublicationTableRow", () => {
  it("renders the publication title", () => {
    const wrapper = mount(PublicationTableRow, { props: defaultProps });
    expect(wrapper.text()).toContain("Test Publication");
  });

  it("renders scholar label", () => {
    const wrapper = mount(PublicationTableRow, { props: defaultProps });
    expect(wrapper.text()).toContain("Dr. Test");
  });

  it("renders year and citation count", () => {
    const wrapper = mount(PublicationTableRow, { props: defaultProps });
    expect(wrapper.text()).toContain("2025");
    expect(wrapper.text()).toContain("42");
  });

  it("shows New badge when is_new_in_latest_run is true", () => {
    const wrapper = mount(PublicationTableRow, { props: defaultProps });
    expect(wrapper.text()).toContain("New");
  });

  it("shows Seen badge when is_new_in_latest_run is false", () => {
    const wrapper = mount(PublicationTableRow, {
      props: { ...defaultProps, item: buildItem({ is_new_in_latest_run: false }) },
    });
    expect(wrapper.text()).toContain("Seen");
  });

  it("shows Unread badge for unread items", () => {
    const wrapper = mount(PublicationTableRow, { props: defaultProps });
    expect(wrapper.text()).toContain("Unread");
  });

  it("shows Read badge for read items", () => {
    const wrapper = mount(PublicationTableRow, {
      props: { ...defaultProps, item: buildItem({ is_read: true }) },
    });
    expect(wrapper.text()).toContain("Read");
  });

  it("disables checkbox when item is read", () => {
    const wrapper = mount(PublicationTableRow, {
      props: { ...defaultProps, item: buildItem({ is_read: true }) },
    });
    const checkbox = wrapper.find('input[type="checkbox"]');
    expect((checkbox.element as HTMLInputElement).disabled).toBe(true);
  });

  it("emits toggle-selection when checkbox is changed", async () => {
    const wrapper = mount(PublicationTableRow, { props: defaultProps });
    await wrapper.find('input[type="checkbox"]').trigger("change");
    expect(wrapper.emitted("toggle-selection")).toHaveLength(1);
  });

  it("emits toggle-favorite when star button is clicked", async () => {
    const wrapper = mount(PublicationTableRow, { props: defaultProps });
    await wrapper.find(".favorite-star-button").trigger("click");
    expect(wrapper.emitted("toggle-favorite")).toHaveLength(1);
  });

  it("shows filled star when item is favorite", () => {
    const wrapper = mount(PublicationTableRow, {
      props: { ...defaultProps, item: buildItem({ is_favorite: true }) },
    });
    expect(wrapper.find(".favorite-star-on").exists()).toBe(true);
    expect(wrapper.text()).toContain("★");
  });

  it("shows empty star when item is not favorite", () => {
    const wrapper = mount(PublicationTableRow, { props: defaultProps });
    expect(wrapper.find(".favorite-star-off").exists()).toBe(true);
    expect(wrapper.text()).toContain("☆");
  });

  it("shows Available link when pdf_url is set", () => {
    const wrapper = mount(PublicationTableRow, {
      props: { ...defaultProps, item: buildItem({ pdf_url: "https://example.com/paper.pdf" }) },
    });
    expect(wrapper.text()).toContain("Available");
  });

  it("shows retry button when canRetry is true and no pdf_url", () => {
    const wrapper = mount(PublicationTableRow, {
      props: { ...defaultProps, canRetry: true },
    });
    expect(wrapper.text()).toContain("Missing (Retry)");
  });

  it("emits retry-pdf when retry button is clicked", async () => {
    const wrapper = mount(PublicationTableRow, {
      props: { ...defaultProps, canRetry: true },
    });
    await wrapper.find(".pdf-retry-button").trigger("click");
    expect(wrapper.emitted("retry-pdf")).toHaveLength(1);
  });

  it("shows Retrying... label when retrying", () => {
    const wrapper = mount(PublicationTableRow, {
      props: { ...defaultProps, canRetry: true, retrying: true },
    });
    expect(wrapper.text()).toContain("Retrying...");
  });
});
