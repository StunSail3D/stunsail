<script setup lang="ts">
import { onMounted, ref } from "vue";
import CardGrid from "../components/CardGrid.vue";
import { download, messageOf, request, type Summary } from "../api";
import { grams, kwh, money } from "../format";

const from = ref("");
const to = ref("");
const summary = ref<Summary | null>(null);
const error = ref("");

// Date inputs are local calendar days; send them as explicit UTC-offset timestamps.
function range(): string {
  const params = new URLSearchParams();
  if (from.value)
    params.set("from", new Date(`${from.value}T00:00:00`).toISOString());
  if (to.value) {
    const end = new Date(`${to.value}T00:00:00`);
    end.setDate(end.getDate() + 1);
    params.set("to", end.toISOString());
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

async function load() {
  try {
    summary.value = await request<Summary>(`/reports/summary${range()}`);
    error.value = "";
  } catch (e) {
    error.value = messageOf(e);
  }
}

async function exportCsv() {
  try {
    await download(`/export/jobs.csv${range()}`, "stunsail-jobs.csv");
    error.value = "";
  } catch (e) {
    error.value = messageOf(e);
  }
}

onMounted(load);
</script>

<template>
  <h1>Reports</h1>
  <form class="grid" @submit.prevent="load">
    <label>From <input v-model="from" type="date" /></label>
    <label>To <input v-model="to" type="date" /></label>
    <button>Show</button>
    <button type="button" @click="exportCsv">Export CSV</button>
  </form>
  <p v-if="error" class="error" role="alert">{{ error }}</p>

  <template v-if="summary">
    <p v-if="summary.mixed_currencies" class="warn">
      Costs span more than one currency, so combined totals are not shown.
      Narrow the date range.
    </p>
    <CardGrid
      page="reports"
      :cards="[{ id: 'summary', title: 'Summary', height: 10 }]"
    >
      <template #summary
        ><section>
          <h2>Summary</h2>
          <dl class="stats">
            <div>
              <dt>Prints</dt>
              <dd>{{ summary.jobs }}</dd>
            </div>
            <div>
              <dt>Filament</dt>
              <dd>{{ grams(summary.filament_g) }}</dd>
            </div>
            <div>
              <dt>Energy (estimated)</dt>
              <dd>{{ kwh(summary.kwh) }}</dd>
            </div>
            <div v-if="!summary.mixed_currencies">
              <dt>Electricity</dt>
              <dd>{{ money(summary.electricity_cost, summary.currency) }}</dd>
            </div>
            <div v-if="!summary.mixed_currencies">
              <dt>Filament cost</dt>
              <dd>{{ money(summary.filament_cost, summary.currency) }}</dd>
            </div>
            <div v-if="!summary.mixed_currencies">
              <dt>Total</dt>
              <dd>{{ money(summary.total_cost, summary.currency) }}</dd>
            </div>
          </dl>
          <p v-if="summary.jobs_without_cost" class="warn">
            {{ summary.jobs_without_cost }} print(s) have no cost recorded and
            are not in the cost totals.
          </p>
        </section></template
      >
    </CardGrid>
    <table v-if="summary.by_month.length && !summary.mixed_currencies">
      <thead>
        <tr>
          <th>Month</th>
          <th>Prints</th>
          <th>Filament</th>
          <th>Energy</th>
          <th class="num">Cost</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in summary.by_month" :key="row.period">
          <td>{{ row.period }}</td>
          <td>{{ row.jobs }}</td>
          <td>{{ grams(row.filament_g) }}</td>
          <td>{{ kwh(row.kwh) }}</td>
          <td class="num">
            {{
              money(
                String(
                  Number(row.electricity_cost) + Number(row.filament_cost),
                ),
                summary.currency,
              )
            }}
          </td>
        </tr>
      </tbody>
    </table>
  </template>
</template>
