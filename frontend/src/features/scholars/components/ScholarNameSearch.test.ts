// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import ScholarNameSearch from "./ScholarNameSearch.vue";

const defaultProps = {
  trackedScholarIds: new Set<string>(),
  addingCandidateScholarId: null,
};

describe("ScholarNameSearch", () => {
  it("renders the search heading", () => {
    const wrapper = mount(ScholarNameSearch, {
      props: defaultProps,
      global: { stubs: { ScholarAvatar: true } },
    });
    expect(wrapper.text()).toContain("Search by Name");
  });

  it("shows WIP badge indicating the feature is incomplete", () => {
    const wrapper = mount(ScholarNameSearch, {
      props: defaultProps,
      global: { stubs: { ScholarAvatar: true } },
    });
    expect(wrapper.text()).toContain("WIP");
  });

  it("renders the search input", () => {
    const wrapper = mount(ScholarNameSearch, {
      props: defaultProps,
      global: { stubs: { ScholarAvatar: true } },
    });
    expect(wrapper.find("form").exists()).toBe(true);
  });

  it("shows warning about Google Scholar login challenges", () => {
    const wrapper = mount(ScholarNameSearch, {
      props: defaultProps,
      global: { stubs: { ScholarAvatar: true } },
    });
    expect(wrapper.text()).toContain("login challenge");
  });
});
