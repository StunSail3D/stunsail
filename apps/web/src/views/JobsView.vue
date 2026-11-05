<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { request, messageOf, type Job } from "../api";
import { dateTime, duration } from "../format";

const PAGE = 25;
const jobs = ref<Job[]>([]);
const state = ref("");
const offset = ref(0);
const error = ref("");
const loaded = ref(false);

async function load() {
  try {
    const params = new URLSearchParams({
      limit: String(PAGE),
      offset: String(offset.value),
    });
    if (state.value) params.set("state", state.value);
    jobs.value = await request<Job[]>(`/jobs?${params}`);
    error.value = "";
  } catch (e) {
    error.value = messageOf(e);
  } finally {
    loaded.value = true;
  }
}

function page(delta: number) {
  offset.value = Math.max(0, offset.value + delta);
  void load();
}

watch(state, () => {
  offset.value = 0;
  void load();
});
onMounted(load);
</script>

<template>
  <h1>Print history</h1>
  <label class="inline">
    State
    <select v-model="state">
      <option value="">All</option>
      <option>completed</option>
      <option>cancelled</option>
      <option>errored</option>
      <option>interrupted</option>
      <option>printing</option>
    </select>
  </label>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <p v-else-if="loaded && !jobs.length" class="empty">
    No prints recorded yet.
  </p>
  <table v-else>
    <thead>
      <tr>
        <th>File</th>
        <th>State</th>
        <th>Started</th>
        <th>Duration</th>
        <th>Spool</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="job in jobs" :key="job.id">
        <td>
          <RouterLink :to="{ name: 'job', params: { id: job.id } }">{{
            job.filename
          }}</RouterLink>
        </td>
        <td>{{ job.state }}</td>
        <td>{{ dateTime(job.started_at) }}</td>
        <td>{{ duration(job.duration_s) }}</td>
        <td>{{ job.spool_id ? "assigned" : "none" }}</td>
      </tr>
    </tbody>
  </table>
  <p class="pager">
    <button :disabled="offset === 0" @click="page(-PAGE)">Newer</button>
    <button :disabled="jobs.length < PAGE" @click="page(PAGE)">Older</button>
  </p>
</template>
