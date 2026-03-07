import { computed, ref, watch, type Ref } from "vue";

import {
  bulkDeleteScholars,
  bulkToggleScholars,
  exportScholarData,
  type ScholarProfile,
} from "@/features/scholars";
import { ApiRequestError } from "@/lib/api/errors";

export type ScholarBulkAction =
  | "delete_selected"
  | "enable_selected"
  | "disable_selected"
  | "export_selected"
  | "clear_selection"
  | "select_all";

export interface ScholarBulkActionOption {
  value: ScholarBulkAction;
  label: string;
}

export interface BulkActionCallbacks {
  clearMessages: () => void;
  assignError: (error: unknown, fallback: string) => void;
  setSuccess: (msg: string) => void;
  reloadScholars: () => Promise<void>;
}

export function useScholarBulkActions(
  visibleScholars: Ref<ScholarProfile[]>,
  callbacks: BulkActionCallbacks,
) {
  const selectedIds = ref<Set<number>>(new Set());
  const bulkAction = ref<ScholarBulkAction>("select_all");
  const bulkBusy = ref(false);

  const selectedCount = computed(() => selectedIds.value.size);
  const hasSelection = computed(() => selectedCount.value > 0);

  const allVisibleSelected = computed(() => {
    if (visibleScholars.value.length === 0) return false;
    for (const item of visibleScholars.value) {
      if (!selectedIds.value.has(item.id)) return false;
    }
    return true;
  });

  const bulkActionOptions = computed<ScholarBulkActionOption[]>(() => {
    if (!hasSelection.value) return [{ value: "select_all", label: "Select all" }];
    const n = selectedCount.value;
    return [
      { value: "delete_selected", label: `Delete selected (${n})` },
      { value: "enable_selected", label: `Enable selected (${n})` },
      { value: "disable_selected", label: `Disable selected (${n})` },
      { value: "export_selected", label: `Export selected (${n})` },
      { value: "clear_selection", label: "Clear selection" },
    ];
  });

  const bulkApplyLabel = computed(() => {
    if (bulkBusy.value) return "Applying...";
    if (bulkAction.value === "select_all") return "Select";
    if (bulkAction.value === "clear_selection") return "Clear";
    return "Apply";
  });

  const bulkApplyDisabled = computed(() => {
    if (bulkBusy.value) return true;
    if (bulkAction.value === "select_all") return visibleScholars.value.length === 0;
    return selectedCount.value === 0;
  });

  // Prune stale selections when visible list changes
  watch(visibleScholars, (items) => {
    const validIds = new Set(items.map((item) => item.id));
    const next = new Set<number>();
    for (const id of selectedIds.value) {
      if (validIds.has(id)) next.add(id);
    }
    if (next.size !== selectedIds.value.size) selectedIds.value = next;
  });

  // Reset bulk action dropdown when selection state changes
  watch(hasSelection, (has) => {
    const validValues = new Set(bulkActionOptions.value.map((o) => o.value));
    if (validValues.has(bulkAction.value)) return;
    bulkAction.value = has ? "delete_selected" : "select_all";
  });

  function onToggleAll(event: Event): void {
    const checked = (event.target as HTMLInputElement).checked;
    const next = new Set(selectedIds.value);
    for (const item of visibleScholars.value) {
      if (checked) { next.add(item.id); } else { next.delete(item.id); }
    }
    selectedIds.value = next;
  }

  function onToggleRow(id: number, event: Event): void {
    const checked = (event.target as HTMLInputElement).checked;
    const next = new Set(selectedIds.value);
    if (checked) { next.add(id); } else { next.delete(id); }
    selectedIds.value = next;
  }

  function downloadJsonFile(filename: string, payload: unknown): void {
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function onApplyBulkAction(): Promise<void> {
    if (bulkApplyDisabled.value) return;
    if (bulkAction.value === "select_all") {
      selectedIds.value = new Set(visibleScholars.value.map((item) => item.id));
      return;
    }
    if (bulkAction.value === "clear_selection") { selectedIds.value = new Set(); return; }
    if (bulkAction.value === "delete_selected") { await onBulkDelete(); return; }
    if (bulkAction.value === "enable_selected") { await onBulkToggle(true); return; }
    if (bulkAction.value === "disable_selected") { await onBulkToggle(false); return; }
    if (bulkAction.value === "export_selected") { await onBulkExport(); return; }
  }

  async function onBulkDelete(): Promise<void> {
    const ids = [...selectedIds.value];
    if (!window.confirm(`Delete ${ids.length} scholar(s)? This removes all linked publications and queue data.`)) return;
    bulkBusy.value = true;
    callbacks.clearMessages();
    try {
      const result = await bulkDeleteScholars(ids);
      callbacks.setSuccess(`${result.deleted_count} scholar(s) deleted.`);
      selectedIds.value = new Set();
      await callbacks.reloadScholars();
    } catch (error) {
      callbacks.assignError(error, "Unable to bulk delete scholars.");
    } finally {
      bulkBusy.value = false;
    }
  }

  async function onBulkToggle(isEnabled: boolean): Promise<void> {
    bulkBusy.value = true;
    callbacks.clearMessages();
    try {
      const ids = [...selectedIds.value];
      const result = await bulkToggleScholars(ids, isEnabled);
      const verb = isEnabled ? "enabled" : "disabled";
      callbacks.setSuccess(`${result.updated_count} scholar(s) ${verb}.`);
      selectedIds.value = new Set();
      await callbacks.reloadScholars();
    } catch (error) {
      callbacks.assignError(error, `Unable to bulk ${isEnabled ? "enable" : "disable"} scholars.`);
    } finally {
      bulkBusy.value = false;
    }
  }

  async function onBulkExport(): Promise<void> {
    bulkBusy.value = true;
    callbacks.clearMessages();
    try {
      const ids = [...selectedIds.value];
      const payload = await exportScholarData(ids);
      const dateSlug = payload.exported_at.slice(0, 10) || "unknown-date";
      downloadJsonFile(`scholarr-export-${dateSlug}.json`, payload);
      callbacks.setSuccess("Export complete.");
    } catch (error) {
      callbacks.assignError(error, "Unable to export selected scholars.");
    } finally {
      bulkBusy.value = false;
    }
  }

  return {
    selectedIds,
    selectedCount,
    hasSelection,
    allVisibleSelected,
    bulkAction,
    bulkBusy,
    bulkActionOptions,
    bulkApplyLabel,
    bulkApplyDisabled,
    onToggleAll,
    onToggleRow,
    onApplyBulkAction,
  };
}
