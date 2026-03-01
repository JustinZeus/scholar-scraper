// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import ScholarBatchAdd from "./ScholarBatchAdd.vue";

const defaultProps = { saving: false, loading: false };

describe("ScholarBatchAdd", () => {
  it("renders the heading and input", () => {
    const wrapper = mount(ScholarBatchAdd, { props: defaultProps });
    expect(wrapper.text()).toContain("Add Scholar Profiles");
    expect(wrapper.find("textarea").exists()).toBe(true);
  });

  it("shows parsed ID count as 0 for empty input", () => {
    const wrapper = mount(ScholarBatchAdd, { props: defaultProps });
    expect(wrapper.text()).toContain("Parsed IDs:");
  });

  it("parses bare scholar IDs from textarea input", async () => {
    const wrapper = mount(ScholarBatchAdd, { props: defaultProps });
    await wrapper.find("textarea").setValue("A-UbBTPM15wL");
    expect(wrapper.text()).toContain("1");
  });

  it("parses scholar IDs from Google Scholar URLs", async () => {
    const wrapper = mount(ScholarBatchAdd, { props: defaultProps });
    await wrapper.find("textarea").setValue(
      "https://scholar.google.com/citations?hl=en&user=A-UbBTPM15wL",
    );
    expect(wrapper.text()).toContain("1");
  });

  it("deduplicates IDs from mixed input", async () => {
    const wrapper = mount(ScholarBatchAdd, { props: defaultProps });
    await wrapper.find("textarea").setValue(
      "A-UbBTPM15wL\nhttps://scholar.google.com/citations?user=A-UbBTPM15wL",
    );
    expect(wrapper.text()).toContain("1");
  });

  it("parses multiple IDs separated by commas", async () => {
    const wrapper = mount(ScholarBatchAdd, { props: defaultProps });
    await wrapper.find("textarea").setValue("A-UbBTPM15wL, B-UbBTPM15wL");
    expect(wrapper.text()).toContain("2");
  });

  it("emits add-scholars with parsed IDs on submit", async () => {
    const wrapper = mount(ScholarBatchAdd, { props: defaultProps });
    await wrapper.find("textarea").setValue("A-UbBTPM15wL");
    await wrapper.find("form").trigger("submit");
    const emitted = wrapper.emitted("add-scholars");
    expect(emitted).toHaveLength(1);
    expect(emitted![0][0]).toEqual(["A-UbBTPM15wL"]);
  });

  it("clears textarea after successful submit", async () => {
    const wrapper = mount(ScholarBatchAdd, { props: defaultProps });
    const textarea = wrapper.find("textarea");
    await textarea.setValue("A-UbBTPM15wL");
    await wrapper.find("form").trigger("submit");
    expect((textarea.element as HTMLTextAreaElement).value).toBe("");
  });

  it("does not emit when input contains no valid IDs", async () => {
    const wrapper = mount(ScholarBatchAdd, { props: defaultProps });
    await wrapper.find("textarea").setValue("not-a-valid-id");
    await wrapper.find("form").trigger("submit");
    expect(wrapper.emitted("add-scholars")).toBeUndefined();
  });

  it("shows Adding... label when saving prop is true", () => {
    const wrapper = mount(ScholarBatchAdd, { props: { ...defaultProps, saving: true } });
    expect(wrapper.text()).toContain("Adding...");
  });
});
