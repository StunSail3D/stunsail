<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { authRequired } from "./api";
import { currencyError, loadCurrency } from "./currency";

const collapsed = ref(window.innerWidth < 768);
const overlayMenu = ref(window.innerWidth < 1200);
let mobile = window.innerWidth < 768;
function updateMenuForWidth() {
  const nextMobile = window.innerWidth < 768;
  overlayMenu.value = window.innerWidth < 1200;
  if (nextMobile !== mobile) {
    mobile = nextMobile;
    collapsed.value = mobile;
  }
}
function closeOverlayMenu() {
  if (overlayMenu.value) collapsed.value = true;
}
onMounted(() => {
  window.addEventListener("resize", updateMenuForWidth);
  void loadCurrency().catch(() => {
    // The error is displayed by the currency settings banner.
  });
});
onUnmounted(() => window.removeEventListener("resize", updateMenuForWidth));
const links = [
  {
    to: "/",
    label: "Dashboard",
    icon: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  },
  {
    to: "/jobs",
    label: "Jobs",
    icon: "M6 3h9l4 4v14H6z M14 3v5h5 M9 13h7 M9 17h7",
  },
  {
    to: "/spools",
    label: "Spools",
    icon: "M5 5h14v14H5z M3 5v14 M21 5v14 M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z",
  },
  {
    to: "/reports",
    label: "Reports",
    icon: "M4 20h16 M6 17v-5 M12 17V5 M18 17V9",
  },
  {
    to: "/settings",
    label: "Settings",
    icon: "M4 7h16 M4 17h16 M8 4v6 M16 14v6",
  },
];
</script>

<template>
  <div
    class="app-shell"
    :class="{ 'menu-collapsed': collapsed }"
    @keydown.esc="closeOverlayMenu"
  >
    <button
      v-if="overlayMenu && !collapsed"
      type="button"
      class="menu-backdrop"
      aria-label="Close menu"
      @click="closeOverlayMenu"
    />
    <aside class="sidebar" aria-label="Main navigation">
      <div class="sidebar-header">
        <button
          type="button"
          class="menu-toggle logo-toggle"
          :aria-label="collapsed ? 'Expand menu' : 'Collapse menu'"
          :aria-expanded="!collapsed"
          aria-controls="main-nav"
          @click="collapsed = !collapsed"
        >
          <img :src="'/logo_icon.svg'" alt="" class="logo-icon" />
        </button>
        <span v-if="!collapsed" class="brand-name">StunSail</span>
      </div>
      <nav id="main-nav">
        <RouterLink
          v-for="link in links"
          :key="link.to"
          :to="link.to"
          :title="collapsed ? link.label : undefined"
          :aria-label="link.label"
          :class="{ 'settings-link': link.to === '/settings' }"
          @click="closeOverlayMenu"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path :d="link.icon" />
          </svg>
          <span v-if="!collapsed">{{ link.label }}</span>
        </RouterLink>
      </nav>
    </aside>
    <div class="page">
      <p v-if="currencyError" class="error" role="alert">
        Could not load currency settings: {{ currencyError }}.
        <button type="button" @click="loadCurrency().catch(() => {})">
          Retry
        </button>
      </p>
      <p v-if="authRequired" class="banner" role="alert">
        The server requires an admin token. Enter it in
        <RouterLink to="/settings">Settings</RouterLink>.
      </p>
      <main><RouterView /></main>
    </div>
  </div>
</template>
