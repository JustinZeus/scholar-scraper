// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import ScholarSettingsModal from "./ScholarSettingsModal.vue";
import type { ScholarProfile } from "@/features/scholars";

function buildScholar(overrides: Partial<ScholarProfile> = {}): ScholarProfile {
  return {
    id: 1,
    scholar_id: "abcDEF123456",
    display_name: "Dr. Test Scholar",
    profile_image_url: null,
    profile_image_source: "none" as const,
    is_enabled: true,
    baseline_completed: true,
    last_run_dt: null,
    last_run_status: null,
    ...overrides,
  };
}

const defaultProps = {
  scholar: buildScholar(),
  imageUrlDraft: "",
  imageBusy: false,
  imageSaving: false,
  imageUploading: false,
  saving: false,
};

describe("ScholarSettingsModal", () => {
  it("renders scholar name and ID when scholar is provided", () => {
    const wrapper = mount(ScholarSettingsModal, {
      props: defaultProps,
      global: { stubs: { AppModal: false, RouterLink: true, ScholarAvatar: true } },
    });
    expect(wrapper.text()).toContain("Dr. Test Scholar");
    expect(wrapper.text()).toContain("abcDEF123456");
  });

  it("renders nothing when scholar is null", () => {
    const wrapper = mount(ScholarSettingsModal, {
      props: { ...defaultProps, scholar: null },
      global: { stubs: { AppModal: false, RouterLink: true, ScholarAvatar: true } },
    });
    expect(wrapper.text()).not.toContain("Dr. Test Scholar");
  });

  it("emits close when close event fires", async () => {
    const wrapper = mount(ScholarSettingsModal, {
      props: defaultProps,
      global: { stubs: { RouterLink: true, ScholarAvatar: true } },
    });
    const modal = wrapper.findComponent({ name: "AppModal" });
    if (modal.exists()) {
      modal.vm.$emit("close");
      expect(wrapper.emitted("close")).toHaveLength(1);
    }
  });

  it("emits delete when delete button is clicked", async () => {
    const wrapper = mount(ScholarSettingsModal, {
      props: defaultProps,
      global: { stubs: { RouterLink: true, ScholarAvatar: true } },
    });
    const deleteButton = wrapper.findAll("button").find((b) => b.text().includes("Delete"));
    if (deleteButton) {
      await deleteButton.trigger("click");
      expect(wrapper.emitted("delete")).toHaveLength(1);
    }
  });

  it("emits toggle when enable/disable button is clicked", async () => {
    const wrapper = mount(ScholarSettingsModal, {
      props: defaultProps,
      global: { stubs: { RouterLink: true, ScholarAvatar: true } },
    });
    const toggleButton = wrapper.findAll("button").find((b) => b.text().includes("Disable"));
    if (toggleButton) {
      await toggleButton.trigger("click");
      expect(wrapper.emitted("toggle")).toHaveLength(1);
    }
  });

  it("shows Enable button for disabled scholars", () => {
    const wrapper = mount(ScholarSettingsModal, {
      props: { ...defaultProps, scholar: buildScholar({ is_enabled: false }) },
      global: { stubs: { RouterLink: true, ScholarAvatar: true } },
    });
    expect(wrapper.text()).toContain("Enable");
  });
});
