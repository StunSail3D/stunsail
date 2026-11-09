<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { GridItem, GridLayout } from "vue-grid-layout-v3";
import { defaultLayout } from "../defaultLayouts";

interface CardDefinition {
  id: string;
  title: string;
  height?: number;
}
interface Position {
  i: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

const props = defineProps<{ page: string; cards: CardDefinition[] }>();
const width = ref(window.innerWidth);
const columns = computed(() =>
  width.value >= 1200 ? 3 : width.value >= 768 ? 2 : 1,
);
const positions = ref<Position[]>([]);
const storageError = ref(false);
const key = computed(() => `stunsail-layout-v1:${props.page}:${columns.value}`);
let savedPositions: Position[] = [];

function updateWidth() {
  width.value = window.innerWidth;
}

function load() {
  let saved: Position[] = [];
  try {
    const raw = localStorage.getItem(key.value);
    const data: unknown = raw ? JSON.parse(raw) : [];
    if (Array.isArray(data)) {
      saved = data.filter(
        (p): p is Position =>
          p &&
          typeof p.i === "string" &&
          [p.x, p.y, p.w, p.h].every(Number.isInteger) &&
          p.x >= 0 &&
          p.y >= 0 &&
          p.w >= 1 &&
          p.h >= 2 &&
          p.x + p.w <= columns.value &&
          p.h <= 100,
      );
    }
    storageError.value = false;
  } catch {
    storageError.value = true;
  }
  savedPositions = saved;
  if (!saved.length) {
    positions.value = defaultLayout(props.page, columns.value, props.cards);
    return;
  }
  let bottom = saved.reduce((max, p) => Math.max(max, p.y + p.h), 0);
  positions.value = props.cards.map((card) => {
    const existing = saved.find((p) => p.i === card.id);
    if (existing) return { ...existing };
    const h = card.height ?? 8;
    const item = { i: card.id, x: 0, y: bottom, w: 1, h };
    bottom += h;
    return item;
  });
}

function save() {
  try {
    const visible = new Set(positions.value.map((position) => position.i));
    savedPositions = [
      ...savedPositions.filter((position) => !visible.has(position.i)),
      ...positions.value.map(({ i, x, y, w, h }) => ({ i, x, y, w, h })),
    ];
    localStorage.setItem(key.value, JSON.stringify(savedPositions));
    storageError.value = false;
  } catch {
    storageError.value = true;
  }
}

function saveAfterUpdate() {
  void nextTick(save);
}

function reset() {
  try {
    localStorage.removeItem(key.value);
    load();
  } catch {
    storageError.value = true;
  }
}

watch([key, () => props.cards.map((card) => card.id).join("\u0000")], load, {
  immediate: true,
});
onMounted(() => window.addEventListener("resize", updateWidth));
onUnmounted(() => window.removeEventListener("resize", updateWidth));
</script>

<template>
  <div class="layout-toolbar">
    <span class="muted small"
      >Drag a card by its handle; resize from its lower corner.</span
    >
    <button type="button" @click="reset">Reset layout</button>
  </div>
  <p v-if="storageError" class="warn" role="alert">
    Layout could not be saved or loaded in this browser.
  </p>
  <GridLayout
    :key="key"
    v-model:layout="positions"
    :col-num="columns"
    :row-height="32"
    :margin="[12, 12]"
    :is-bounded="true"
    :vertical-compact="true"
  >
    <GridItem
      v-for="item in positions"
      :key="item.i"
      :i="item.i"
      :x="item.x"
      :y="item.y"
      :w="item.w"
      :h="item.h"
      :min-h="2"
      :max-h="100"
      drag-allow-from=".card-handle"
      @moved="saveAfterUpdate"
      @resized="saveAfterUpdate"
    >
      <div class="grid-card card">
        <div
          class="card-handle"
          :aria-label="`Drag ${cards.find((c) => c.id === item.i)?.title}`"
          title="Drag card"
        >
          ⠿ Drag
        </div>
        <div class="card-content" tabindex="0"><slot :name="item.i" /></div>
      </div>
    </GridItem>
  </GridLayout>
</template>
