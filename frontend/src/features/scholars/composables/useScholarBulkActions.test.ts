// @vitest-environment happy-dom
import { describe, expect, it, vi } from "vitest";
import { nextTick, ref } from "vue";
import { useScholarBulkActions, type ScholarBulkAction } from "./useScholarBulkActions";
import type { ScholarProfile } from "@/features/scholars";

vi.mock("@/features/scholars", () => ({
  bulkDeleteScholars: vi.fn(),
  bulkToggleScholars: vi.fn(),
  exportScholarData: vi.fn(),
}));

function makeProfile(id: number, name: string): ScholarProfile {
  return {
    id,
    scholar_id: `scholar_${id}`,
    display_name: name,
    profile_image_url: null,
    profile_image_source: "none",
    is_enabled: true,
    baseline_completed: false,
    last_run_dt: null,
    last_run_status: null,
  };
}

function setup(profiles: ScholarProfile[] = []) {
  const visibleScholars = ref(profiles);
  const callbacks = {
    clearMessages: vi.fn(),
    assignError: vi.fn(),
    setSuccess: vi.fn(),
    reloadScholars: vi.fn(async () => {}),
  };
  const bulk = useScholarBulkActions(visibleScholars, callbacks);
  return { visibleScholars, callbacks, bulk };
}

describe("useScholarBulkActions", () => {
  it("starts with empty selection", () => {
    const { bulk } = setup([makeProfile(1, "Alice")]);
    expect(bulk.selectedIds.value.size).toBe(0);
    expect(bulk.hasSelection.value).toBe(false);
  });

  it("toggles individual row selection", () => {
    const { bulk } = setup([makeProfile(1, "Alice"), makeProfile(2, "Bob")]);
    bulk.onToggleRow(1, { target: { checked: true } } as unknown as Event);
    expect(bulk.selectedIds.value.has(1)).toBe(true);
    expect(bulk.selectedCount.value).toBe(1);

    bulk.onToggleRow(1, { target: { checked: false } } as unknown as Event);
    expect(bulk.selectedIds.value.has(1)).toBe(false);
    expect(bulk.selectedCount.value).toBe(0);
  });

  it("toggles all visible scholars", () => {
    const { bulk } = setup([makeProfile(1, "Alice"), makeProfile(2, "Bob")]);
    bulk.onToggleAll({ target: { checked: true } } as unknown as Event);
    expect(bulk.selectedIds.value.size).toBe(2);
    expect(bulk.allVisibleSelected.value).toBe(true);

    bulk.onToggleAll({ target: { checked: false } } as unknown as Event);
    expect(bulk.selectedIds.value.size).toBe(0);
  });

  it("prunes stale selections when list changes", async () => {
    const { visibleScholars, bulk } = setup([makeProfile(1, "Alice"), makeProfile(2, "Bob")]);
    bulk.onToggleAll({ target: { checked: true } } as unknown as Event);
    expect(bulk.selectedIds.value.size).toBe(2);

    // Remove Bob from the visible list
    visibleScholars.value = [makeProfile(1, "Alice")];
    await nextTick();

    expect(bulk.selectedIds.value.size).toBe(1);
    expect(bulk.selectedIds.value.has(1)).toBe(true);
    expect(bulk.selectedIds.value.has(2)).toBe(false);
  });

  it("shows correct bulk action options with and without selection", () => {
    const { bulk } = setup([makeProfile(1, "Alice")]);
    // Without selection
    expect(bulk.bulkActionOptions.value.length).toBe(1);
    expect(bulk.bulkActionOptions.value[0].value).toBe("select_all");

    // With selection
    bulk.onToggleRow(1, { target: { checked: true } } as unknown as Event);
    expect(bulk.bulkActionOptions.value.length).toBe(5);
    const values = bulk.bulkActionOptions.value.map((o) => o.value);
    expect(values).toContain("delete_selected");
    expect(values).toContain("enable_selected");
    expect(values).toContain("disable_selected");
    expect(values).toContain("export_selected");
    expect(values).toContain("clear_selection");
  });

  it("select all action selects all visible", async () => {
    const { bulk } = setup([makeProfile(1, "Alice"), makeProfile(2, "Bob")]);
    bulk.bulkAction.value = "select_all" as ScholarBulkAction;
    await bulk.onApplyBulkAction();
    expect(bulk.selectedIds.value.size).toBe(2);
  });

  it("clear selection action clears all", async () => {
    const { bulk } = setup([makeProfile(1, "Alice")]);
    bulk.onToggleRow(1, { target: { checked: true } } as unknown as Event);
    bulk.bulkAction.value = "clear_selection" as ScholarBulkAction;
    await bulk.onApplyBulkAction();
    expect(bulk.selectedIds.value.size).toBe(0);
  });
});
