<script setup lang="ts">
import { authRequired } from "./api";
</script>

<template>
  <header class="top">
    <span class="brand">StunSail</span>
    <nav>
      <RouterLink to="/">Dashboard</RouterLink>
      <RouterLink to="/jobs">Jobs</RouterLink>
      <RouterLink to="/spools">Spools</RouterLink>
      <RouterLink to="/reports">Reports</RouterLink>
      <RouterLink to="/settings">Settings</RouterLink>
    </nav>
  </header>
  <p v-if="authRequired" class="banner" role="alert">
    The server requires an admin token. Enter it in
    <RouterLink to="/settings">Settings</RouterLink>.
  </p>
  <main>
    <RouterView />
  </main>
</template>
