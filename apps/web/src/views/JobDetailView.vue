<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import CardGrid from "../components/CardGrid.vue";
import { request, messageOf, type JobDetail, type Spool } from "../api";
import {
  basisLabel,
  coverage,
  dateTime,
  duration,
  grams,
  kwh,
  money,
} from "../format";

const props = defineProps<{ id: string }>();

const job = ref<JobDetail | null>(null);
const spools = ref<Spool[]>([]);
const chosen = ref("");
const error = ref("");
const busy = ref(false);
const gridCards = computed(() => [
  { id: "cost", title: "Cost", height: 10 },
  ...(job.value?.energy ? [{ id: "energy", title: "Energy", height: 10 }] : []),
  { id: "spool", title: "Filament spool", height: 7 },
]);

const LOW_COVERAGE = 0.9;
const electricity = computed(() =>
  job.value?.costs.find((c) => c.kind === "electricity"),
);
const filament = computed(() =>
  job.value?.costs.find((c) => c.kind === "filament"),
);
const energyCoverage = computed(() =>
  job.value?.energy
    ? coverage(job.value.energy.covered_s, job.value.energy.uncovered_s)
    : 1,
);
const assigned = computed(() =>
  spools.value.find((s) => s.id === job.value?.spool_id),
);
const activeSpools = computed(() =>
  spools.value.filter((s) => s.status === "active"),
);
const lines = computed(
  () =>
    (electricity.value?.details.lines as
      { rate_per_kwh: string; kwh: number; cost: string }[] | undefined) ?? [],
);

async function load() {
  try {
    job.value = await request<JobDetail>(`/jobs/${props.id}`);
    spools.value = await request<Spool[]>("/spools?limit=200");
    error.value = "";
  } catch (e) {
    error.value = messageOf(e);
  }
}

async function act(path: string, body?: unknown) {
  busy.value = true;
  try {
    job.value = await request<JobDetail>(path, "POST", body ?? {});
    spools.value = await request<Spool[]>("/spools?limit=200");
    error.value = "";
  } catch (e) {
    error.value = messageOf(e);
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <p><RouterLink to="/jobs">← All prints</RouterLink></p>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <template v-if="job">
    <h1>{{ job.filename }}</h1>
    <p class="muted">
      {{ job.state }} · {{ dateTime(job.started_at) }} ·
      {{ duration(job.duration_s) }}
      <template v-if="!job.finalised_at"> · not finalised yet</template>
    </p>

    <CardGrid page="job-detail" :cards="gridCards">
      <template #cost
        ><section>
          <h2>Cost</h2>
          <p v-if="!job.costs.length" class="muted">
            No cost recorded.
            <template v-if="!job.energy"
              >The printer needs a calibration profile and tariff.</template
            >
            <template v-else
              >Add a tariff, or assign a spool that has a purchase
              price.</template
            >
          </p>
          <table v-else>
            <tbody>
              <tr v-if="electricity">
                <td>Electricity</td>
                <td>{{ kwh(job.energy?.kwh) }}</td>
                <td class="num">
                  {{ money(electricity.amount, electricity.currency) }}
                </td>
              </tr>
              <tr v-for="(line, i) in lines" :key="i" class="sub">
                <td colspan="2">
                  {{ line.kwh.toFixed(4) }} kWh @ {{ line.rate_per_kwh }} /kWh
                </td>
                <td class="num">{{ line.cost }}</td>
              </tr>
              <tr v-if="filament">
                <td>Filament</td>
                <td>{{ grams(String(filament.details.mass_g)) }}</td>
                <td class="num">
                  {{ money(filament.amount, filament.currency) }}
                </td>
              </tr>
              <tr class="total">
                <td colspan="2">Total</td>
                <td class="num">
                  {{
                    job.total_cost == null
                      ? "mixed currencies"
                      : money(job.total_cost, job.total_cost_currency)
                  }}
                </td>
              </tr>
            </tbody>
          </table>
          <p v-if="filament" class="muted small">
            Filament weight is estimated from length, diameter and density.
          </p>
        </section></template
      >

      <template #energy
        ><section v-if="job.energy">
          <h2>Energy</h2>
          <p>
            <span
              class="pill"
              :class="{ estimated: job.energy.basis === 'estimated' }"
            >
              {{ basisLabel(job.energy.basis) }}
            </span>
            profile v{{ job.energy.profile_version }}, revision
            {{ job.energy.revision }}
          </p>
          <p
            :class="{ warn: energyCoverage < LOW_COVERAGE }"
            data-test="coverage"
          >
            Coverage {{ Math.round(energyCoverage * 100) }}% ({{
              Math.round(job.energy.uncovered_s)
            }}s uncovered, {{ job.energy.invalid_samples }} invalid samples).
            Gaps are not estimated, so energy may be understated.
          </p>
          <button
            :disabled="busy || !job.finalised_at"
            @click="act(`/jobs/${job.id}/recalculate`)"
          >
            Recalculate
          </button>
        </section></template
      >

      <template #spool
        ><section>
          <h2>Filament spool</h2>
          <p v-if="assigned">
            Used <strong>{{ assigned.name }}</strong> ({{ assigned.material }}).
            A spool cannot be changed once assigned.
          </p>
          <form
            v-else
            @submit.prevent="act(`/jobs/${job.id}/spool`, { spool_id: chosen })"
          >
            <select v-model="chosen" required aria-label="Spool">
              <option value="" disabled>Choose a spool…</option>
              <option v-for="s in activeSpools" :key="s.id" :value="s.id">
                {{ s.name }} — {{ s.material }} ({{ grams(s.remaining_g) }}
                left)
              </option>
            </select>
            <button :disabled="busy || !chosen">Assign</button>
          </form>
        </section></template
      >
    </CardGrid>
  </template>
</template>
