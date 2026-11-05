<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import {
  request,
  messageOf,
  type Job,
  type Live,
  type Printer,
  type Summary,
} from "../api";
import { dateTime, duration, kwh, money } from "../format";

const STALE_AFTER_S = 30;
const POLL_MS = 5000;

interface Card {
  printer: Printer;
  live: Live | null;
}

const cards = ref<Card[]>([]);
const recent = ref<Job[]>([]);
const month = ref<Summary | null>(null);
const error = ref("");
const loaded = ref(false);
let timer: ReturnType<typeof setInterval> | undefined;

const num = (group: string, key: string, live: Live | null): number | null => {
  const value = live?.status?.[group]?.[key];
  return typeof value === "number" ? value : null;
};
const temp = (value: number | null) =>
  value == null ? "—" : `${value.toFixed(1)} °C`;

function monthStart(): string {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), 1).toISOString();
}

async function refresh() {
  try {
    const printers = await request<Printer[]>("/printers");
    cards.value = await Promise.all(
      printers.map(async (printer) => ({
        printer,
        live: await request<Live>(`/printers/${printer.id}/live`),
      })),
    );
    recent.value = await request<Job[]>("/jobs?limit=5");
    month.value = await request<Summary>(
      `/reports/summary?from=${encodeURIComponent(monthStart())}`,
    );
    error.value = "";
  } catch (e) {
    error.value = messageOf(e);
  } finally {
    loaded.value = true;
  }
}

onMounted(() => {
  void refresh();
  timer = setInterval(refresh, POLL_MS);
});
onUnmounted(() => clearInterval(timer));
</script>

<template>
  <h1>Dashboard</h1>
  <p v-if="error" class="error" role="alert">{{ error }}</p>

  <p v-if="loaded && !error && cards.length === 0" class="empty">
    No printer yet. Register your Agent and add a printer in
    <RouterLink to="/settings">Settings</RouterLink>.
  </p>

  <section v-for="card in cards" :key="card.printer.id" class="card">
    <h2>{{ card.printer.name }}</h2>
    <p v-if="!card.live?.sample_observed_at" class="muted">
      No data received from the Agent yet.
    </p>
    <template v-else>
      <p
        v-if="(card.live.sample_age_s ?? 0) > STALE_AFTER_S"
        class="warn"
        data-test="stale"
      >
        Last data {{ duration(card.live.sample_age_s) }} ago. The Agent may be
        offline.
      </p>
      <p v-if="card.live.active_job" class="lead">
        <span class="pill">{{ card.live.active_job.state }}</span>
        {{ card.live.active_job.filename }}
        <span class="muted">
          {{ duration(num("print_stats", "print_duration", card.live)) }}
          printed
          <template v-if="num('virtual_sdcard', 'progress', card.live) != null">
            ·
            {{
              Math.round(
                (num("virtual_sdcard", "progress", card.live) ?? 0) * 100,
              )
            }}%
          </template>
        </span>
      </p>
      <p v-else class="lead muted">Idle</p>
      <dl class="stats">
        <div>
          <dt>Hotend</dt>
          <dd>
            {{ temp(num("extruder", "temperature", card.live)) }}
            <small>/ {{ temp(num("extruder", "target", card.live)) }}</small>
          </dd>
        </div>
        <div>
          <dt>Bed</dt>
          <dd>
            {{ temp(num("heater_bed", "temperature", card.live)) }}
            <small>/ {{ temp(num("heater_bed", "target", card.live)) }}</small>
          </dd>
        </div>
      </dl>
    </template>
  </section>

  <section v-if="month" class="card">
    <h2>This month</h2>
    <dl class="stats">
      <div>
        <dt>Prints</dt>
        <dd>{{ month.jobs }}</dd>
      </div>
      <div>
        <dt>Energy</dt>
        <dd>{{ kwh(month.kwh) }}</dd>
      </div>
      <div>
        <dt>Total cost</dt>
        <dd>
          {{
            month.mixed_currencies
              ? "mixed currencies"
              : money(month.total_cost, month.currency)
          }}
        </dd>
      </div>
    </dl>
    <p v-if="month.jobs_without_cost" class="warn">
      {{ month.jobs_without_cost }} print(s) have no cost yet (missing profile,
      spool or tariff).
    </p>
  </section>

  <section v-if="recent.length" class="card">
    <h2>Recent prints</h2>
    <table>
      <tbody>
        <tr v-for="job in recent" :key="job.id">
          <td>
            <RouterLink :to="{ name: 'job', params: { id: job.id } }">{{
              job.filename
            }}</RouterLink>
          </td>
          <td>{{ job.state }}</td>
          <td>{{ dateTime(job.started_at) }}</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>
