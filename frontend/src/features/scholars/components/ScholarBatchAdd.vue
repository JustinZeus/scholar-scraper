<script setup lang="ts">
import { computed, ref } from "vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppHelpHint from "@/components/ui/AppHelpHint.vue";

defineProps<{
  saving: boolean;
  loading: boolean;
}>();

const emit = defineEmits<{
  (e: "add-scholars", ids: string[]): void;
}>();

const scholarBatchInput = ref("");

const SCHOLAR_ID_PATTERN = /^[a-zA-Z0-9_-]{12}$/;
const URL_USER_PARAM_PATTERN = /(?:\?|&)user=([a-zA-Z0-9_-]{12})(?:&|#|$)/i;

function parseScholarIds(raw: string): string[] {
  const ordered: string[] = [];
  const seen = new Set<string>();
  const tokens = raw.split(/[\s,;]+/).map((v) => v.trim()).filter((v) => v.length > 0);
  for (const token of tokens) {
    let candidate: string | null = null;
    if (SCHOLAR_ID_PATTERN.test(token)) candidate = token;
    if (!candidate) {
      const directParamMatch = token.match(URL_USER_PARAM_PATTERN);
      if (directParamMatch) candidate = directParamMatch[1];
    }
    if (!candidate && token.includes("scholar.google")) {
      try {
        const parsed = new URL(token);
        const userParam = parsed.searchParams.get("user");
        if (userParam && SCHOLAR_ID_PATTERN.test(userParam)) candidate = userParam;
      } catch (_error) { /* Ignore non-URL tokens. */ }
    }
    if (!candidate || seen.has(candidate)) continue;
    seen.add(candidate);
    ordered.push(candidate);
  }
  return ordered;
}

const parsedBatchCount = computed(() => parseScholarIds(scholarBatchInput.value).length);

function onSubmit(): void {
  const ids = parseScholarIds(scholarBatchInput.value);
  if (ids.length > 0) {
    emit("add-scholars", ids);
    scholarBatchInput.value = "";
  }
}
</script>

<template>
  <AppCard class="space-y-4 xl:flex xl:min-h-0 xl:flex-col">
    <div class="space-y-1">
      <div class="flex items-center gap-1">
        <h2 class="text-lg font-semibold text-ink-primary">Add Scholar Profiles</h2>
        <AppHelpHint text="A scholar profile is a Google Scholar author page that Scholarr will monitor for publication changes." />
      </div>
      <p class="text-sm text-secondary">Paste one or more Scholar IDs or profile URLs and add them in one action.</p>
    </div>

    <form class="grid gap-3" @submit.prevent="onSubmit">
      <label class="grid gap-2 text-sm font-medium text-ink-secondary" for="scholar-batch-input">
        <span>Scholar IDs or profile URLs</span>
        <textarea
          id="scholar-batch-input"
          v-model="scholarBatchInput"
          rows="5"
          placeholder="A-UbBTPM15wL&#10;https://scholar.google.com/citations?hl=en&user=A-UbBTPM15wL"
          class="w-full rounded-lg border border-stroke-interactive bg-surface-input px-3 py-2 text-sm text-ink-primary outline-none ring-focus-ring transition placeholder:text-ink-muted focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset disabled:cursor-not-allowed disabled:opacity-60"
        />
      </label>

      <div class="flex flex-wrap items-center justify-between gap-2">
        <p class="text-xs text-secondary">
          Parsed IDs: <strong class="text-ink-primary">{{ parsedBatchCount }}</strong>
        </p>
        <AppButton type="submit" :disabled="saving || loading">
          {{ saving ? "Adding..." : "Add scholars" }}
        </AppButton>
      </div>
    </form>
  </AppCard>
</template>
