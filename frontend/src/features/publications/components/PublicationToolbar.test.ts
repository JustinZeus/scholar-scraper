// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import PublicationToolbar from "./PublicationToolbar.vue";

const defaultProps = {
  mode: "all" as const,
  selectedScholarFilter: "",
  searchQuery: "",
  favoriteOnly: false,
  actionBusy: false,
  loading: false,
  scholars: [],
  startRunDisabled: false,
  startRunDisabledReason: null,
  startRunButtonLabel: "Check now",
};

describe("PublicationToolbar", () => {
  it("renders mode, scholar filter, and search inputs", () => {
    const wrapper = mount(PublicationToolbar, { props: defaultProps });
    expect(wrapper.text()).toContain("Status");
    expect(wrapper.text()).toContain("Scholar");
    expect(wrapper.text()).toContain("Search");
  });

  it("renders the start run button with provided label", () => {
    const wrapper = mount(PublicationToolbar, { props: defaultProps });
    expect(wrapper.text()).toContain("Check now");
  });

  it("disables start run button when startRunDisabled is true", () => {
    const wrapper = mount(PublicationToolbar, {
      props: { ...defaultProps, startRunDisabled: true, startRunDisabledReason: "Cooldown active" },
    });
    const buttons = wrapper.findAll("button");
    const runButton = buttons.find((b) => b.text().includes("Check now"));
    expect(runButton?.attributes("disabled")).toBeDefined();
  });

  it("emits start-run when start button is clicked", async () => {
    const wrapper = mount(PublicationToolbar, { props: defaultProps });
    const buttons = wrapper.findAll("button");
    const runButton = buttons.find((b) => b.text().includes("Check now"));
    await runButton?.trigger("click");
    expect(wrapper.emitted("start-run")).toHaveLength(1);
  });

  it("emits favorite-only-changed when star filter is clicked", async () => {
    const wrapper = mount(PublicationToolbar, { props: defaultProps });
    await wrapper.find(".favorite-filter-button").trigger("click");
    expect(wrapper.emitted("favorite-only-changed")).toHaveLength(1);
  });

  it("shows active star filter style when favoriteOnly is true", () => {
    const wrapper = mount(PublicationToolbar, { props: { ...defaultProps, favoriteOnly: true } });
    expect(wrapper.find(".favorite-filter-on").exists()).toBe(true);
  });

  it("shows inactive star filter style when favoriteOnly is false", () => {
    const wrapper = mount(PublicationToolbar, { props: defaultProps });
    expect(wrapper.find(".favorite-filter-off").exists()).toBe(true);
  });

  it("renders scholar options from props", () => {
    const scholars = [
      { id: 1, scholar_id: "abc123", display_name: "Alice", profile_image_url: null, profile_image_source: "none" as const, is_enabled: true, baseline_completed: true, last_run_dt: null, last_run_status: null },
      { id: 2, scholar_id: "def456", display_name: "", profile_image_url: null, profile_image_source: "none" as const, is_enabled: true, baseline_completed: true, last_run_dt: null, last_run_status: null },
    ];
    const wrapper = mount(PublicationToolbar, { props: { ...defaultProps, scholars } });
    expect(wrapper.text()).toContain("Alice");
    expect(wrapper.text()).toContain("def456");
  });

  it("shows clear button only when search query is non-empty", () => {
    const empty = mount(PublicationToolbar, { props: defaultProps });
    expect(empty.text()).not.toContain("Clear");

    const withQuery = mount(PublicationToolbar, { props: { ...defaultProps, searchQuery: "test" } });
    expect(withQuery.text()).toContain("Clear");
  });

  it("emits reset-search when clear button is clicked", async () => {
    const wrapper = mount(PublicationToolbar, { props: { ...defaultProps, searchQuery: "test" } });
    const clearButton = wrapper.findAll("button").find((b) => b.text().includes("Clear"));
    await clearButton?.trigger("click");
    expect(wrapper.emitted("reset-search")).toHaveLength(1);
  });
});
