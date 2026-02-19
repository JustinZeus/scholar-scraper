<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useSlots, watch } from "vue";

type TooltipSide = "right" | "left" | "top" | "bottom";

const props = withDefaults(
  defineProps<{
    text: string;
    side?: TooltipSide | "auto";
  }>(),
  {
    side: "auto",
  },
);
const slots = useSlots();

const GAP = 8;
const EDGE_PADDING = 8;

const triggerRef = ref<HTMLElement | null>(null);
const tooltipRef = ref<HTMLElement | null>(null);
const isOpen = ref(false);
const resolvedSide = ref<TooltipSide>("top");
const tooltipStyle = ref<Record<string, string>>({
  left: "0px",
  top: "0px",
});

const sideClass = computed(() => {
  if (resolvedSide.value === "left") {
    return "origin-right";
  }
  if (resolvedSide.value === "right") {
    return "origin-left";
  }
  if (resolvedSide.value === "bottom") {
    return "origin-top";
  }
  return "origin-bottom";
});
const hasTriggerSlot = computed(() => Boolean(slots.trigger));

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}

function spaceBySide(rect: DOMRect): Record<TooltipSide, number> {
  return {
    top: rect.top,
    right: window.innerWidth - rect.right,
    bottom: window.innerHeight - rect.bottom,
    left: rect.left,
  };
}

function preferredSides(): TooltipSide[] {
  const allSides: TooltipSide[] = ["top", "right", "bottom", "left"];
  if (!props.side || props.side === "auto") {
    return allSides;
  }
  return [props.side, ...allSides.filter((item) => item !== props.side)];
}

function chooseSide(rect: DOMRect, tooltipRect: DOMRect): TooltipSide {
  const spaces = spaceBySide(rect);
  const order = preferredSides();

  for (const side of order) {
    if (side === "top" || side === "bottom") {
      if (spaces[side] >= tooltipRect.height + GAP) {
        return side;
      }
      continue;
    }
    if (spaces[side] >= tooltipRect.width + GAP) {
      return side;
    }
  }

  return order.sort((left, right) => spaces[right] - spaces[left])[0] ?? "top";
}

function updatePosition(): void {
  if (!isOpen.value || !triggerRef.value || !tooltipRef.value) {
    return;
  }

  const trigger = triggerRef.value.getBoundingClientRect();
  const tooltip = tooltipRef.value.getBoundingClientRect();
  const side = chooseSide(trigger, tooltip);
  resolvedSide.value = side;

  let left = 0;
  let top = 0;

  if (side === "top") {
    left = trigger.left + trigger.width / 2 - tooltip.width / 2;
    top = trigger.top - tooltip.height - GAP;
  } else if (side === "bottom") {
    left = trigger.left + trigger.width / 2 - tooltip.width / 2;
    top = trigger.bottom + GAP;
  } else if (side === "left") {
    left = trigger.left - tooltip.width - GAP;
    top = trigger.top + trigger.height / 2 - tooltip.height / 2;
  } else {
    left = trigger.right + GAP;
    top = trigger.top + trigger.height / 2 - tooltip.height / 2;
  }

  left = clamp(left, EDGE_PADDING, window.innerWidth - tooltip.width - EDGE_PADDING);
  top = clamp(top, EDGE_PADDING, window.innerHeight - tooltip.height - EDGE_PADDING);

  tooltipStyle.value = {
    left: `${Math.round(left)}px`,
    top: `${Math.round(top)}px`,
  };
}

function closeTooltip(): void {
  isOpen.value = false;
}

function openTooltip(): void {
  isOpen.value = true;
  void nextTick(() => {
    updatePosition();
  });
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    closeTooltip();
  }
}

function onViewportChange(): void {
  if (!isOpen.value) {
    return;
  }
  updatePosition();
}

watch(isOpen, (open) => {
  if (open) {
    window.addEventListener("resize", onViewportChange);
    window.addEventListener("scroll", onViewportChange, true);
    window.addEventListener("keydown", onKeydown);
    return;
  }

  window.removeEventListener("resize", onViewportChange);
  window.removeEventListener("scroll", onViewportChange, true);
  window.removeEventListener("keydown", onKeydown);
});

watch(
  () => props.text,
  () => {
    if (isOpen.value) {
      void nextTick(() => {
        updatePosition();
      });
    }
  },
);

onBeforeUnmount(() => {
  window.removeEventListener("resize", onViewportChange);
  window.removeEventListener("scroll", onViewportChange, true);
  window.removeEventListener("keydown", onKeydown);
});
</script>

<template>
  <span class="relative inline-flex items-center align-middle">
    <component
      :is="hasTriggerSlot ? 'span' : 'button'"
      ref="triggerRef"
      :type="hasTriggerSlot ? undefined : 'button'"
      :tabindex="hasTriggerSlot ? 0 : undefined"
      class="inline-flex items-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset"
      :class="
        hasTriggerSlot
          ? 'cursor-help rounded-sm'
          : 'h-5 w-5 justify-center rounded-full border border-stroke-interactive/80 bg-surface-card-muted/80 text-[11px] font-semibold text-ink-secondary transition hover:bg-action-secondary-hover-bg'
      "
      :aria-label="text"
      @mouseenter="openTooltip"
      @mouseleave="closeTooltip"
      @focus="openTooltip"
      @blur="closeTooltip"
    >
      <slot v-if="hasTriggerSlot" name="trigger" />
      <template v-else>?</template>
    </component>
    <Teleport to="body">
      <span
        v-if="isOpen"
        ref="tooltipRef"
        role="tooltip"
        :style="tooltipStyle"
        :class="sideClass"
        class="pointer-events-none fixed z-[90] w-64 max-w-[calc(100vw-2rem)] rounded-lg border border-stroke-default bg-surface-card/95 px-2.5 py-2 text-xs leading-relaxed text-ink-secondary shadow-lg"
      >
        {{ text }}
      </span>
    </Teleport>
  </span>
</template>
