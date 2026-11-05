<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import {
  getToken,
  messageOf,
  request,
  setToken,
  type Printer,
  type Profile,
  type Tariff,
} from "../api";
import { dateTime } from "../format";
import { FormError, profilePayload } from "../profileForm";

interface Agent {
  id: string;
  name: string;
  last_sync_at: string | null;
}

const error = ref("");
const notice = ref("");
const token = ref(getToken());
const agents = ref<Agent[]>([]);
const printers = ref<Printer[]>([]);
const profiles = ref<Profile[]>([]);
const tariffs = ref<Tariff[]>([]);
const newToken = ref<{ agent: string; token: string } | null>(null);

const agentForm = reactive({ agent_id: "", name: "" });
const printerForm = reactive({ agent_id: "", name: "", model: "" });
const tariffForm = reactive({
  currency: "ZAR",
  rate: "",
  from: `${new Date().getFullYear()}-01-01T00:00`,
});
const profileForm = reactive({
  name: "",
  version: 1,
  bedW: 220,
  hotendW: 60,
  baseLoadW: 15,
  externalAcW: 0,
  psuRatedW: 350,
  curve: "0.05:0.72, 0.10:0.80, 0.20:0.86, 0.50:0.89, 1.0:0.89",
  fans: "fan: 3, heater_fan hotend_Fan: 2",
  calibrated: false,
});

async function load() {
  try {
    agents.value = await request<Agent[]>("/agents");
    printers.value = await request<Printer[]>("/printers");
    profiles.value = await request<Profile[]>("/calibration-profiles");
    tariffs.value = await request<Tariff[]>("/tariffs");
    error.value = "";
  } catch (e) {
    error.value = messageOf(e);
  }
}

async function guarded(action: () => Promise<void>) {
  notice.value = "";
  try {
    await action();
    error.value = "";
    await load();
  } catch (e) {
    error.value = e instanceof FormError ? e.message : messageOf(e);
  }
}

function saveToken() {
  setToken(token.value.trim());
  notice.value = token.value
    ? "Admin token saved in this browser."
    : "Admin token cleared.";
  void load();
}

const registerAgent = () =>
  guarded(async () => {
    const result = await request<{ agent_id: string; token: string }>(
      "/agents",
      "POST",
      {
        agent_id: agentForm.agent_id,
        name: agentForm.name,
      },
    );
    newToken.value = { agent: result.agent_id, token: result.token };
    agentForm.agent_id = "";
    agentForm.name = "";
  });

const addPrinter = () =>
  guarded(async () => {
    await request("/printers", "POST", {
      agent_id: printerForm.agent_id,
      name: printerForm.name,
      model: printerForm.model || null,
    });
    printerForm.name = "";
    printerForm.model = "";
  });

const assignProfile = (printer: Printer, profileId: string) =>
  guarded(async () => {
    await request(`/printers/${printer.id}`, "PATCH", {
      calibration_profile_id: profileId,
    });
  });

const addTariff = () =>
  guarded(async () => {
    await request("/tariffs", "POST", {
      currency: tariffForm.currency,
      rate_per_kwh: tariffForm.rate,
      effective_from: new Date(tariffForm.from).toISOString(),
    });
    tariffForm.rate = "";
  });

const addProfile = () =>
  guarded(async () => {
    await request("/calibration-profiles", "POST", profilePayload(profileForm));
    profileForm.version += 1;
  });

onMounted(load);
</script>

<template>
  <h1>Settings</h1>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <p v-if="notice" class="notice">{{ notice }}</p>

  <section class="card">
    <h2>Admin token</h2>
    <form @submit.prevent="saveToken">
      <input
        v-model="token"
        type="password"
        autocomplete="off"
        aria-label="Admin token"
      />
      <button>Save</button>
    </form>
    <p class="muted small">
      Only needed if the server sets STUNSAIL_ADMIN_TOKEN. It is stored in this
      browser. Without a token set on the server, anyone on your network can
      change settings.
    </p>
  </section>

  <section class="card">
    <h2>Agents</h2>
    <ul>
      <li v-for="a in agents" :key="a.id">
        {{ a.name }} <code>{{ a.id }}</code>
        <span class="muted">last sync {{ dateTime(a.last_sync_at) }}</span>
      </li>
    </ul>
    <form class="grid" @submit.prevent="registerAgent">
      <label>
        Agent id
        <input
          v-model="agentForm.agent_id"
          required
          pattern="[A-Za-z0-9._-]+"
        />
      </label>
      <label>Name <input v-model="agentForm.name" required /></label>
      <button>Register agent</button>
    </form>
    <div v-if="newToken" class="notice" data-test="agent-token">
      Token for <code>{{ newToken.agent }}</code> (shown once; set it as
      <code>STUNSAIL_AGENT_TOKEN</code> on the Agent host):
      <code class="token">{{ newToken.token }}</code>
    </div>
  </section>

  <section class="card">
    <h2>Printers</h2>
    <table v-if="printers.length">
      <tbody>
        <tr v-for="p in printers" :key="p.id">
          <td>{{ p.name }}</td>
          <td>
            <code>{{ p.agent_id }}</code>
          </td>
          <td>
            <select
              :value="p.calibration_profile_id ?? ''"
              :aria-label="`Power profile for ${p.name}`"
              @change="
                assignProfile(p, ($event.target as HTMLSelectElement).value)
              "
            >
              <option value="" disabled>No power profile</option>
              <option v-for="pr in profiles" :key="pr.id" :value="pr.id">
                {{ pr.name }} v{{ pr.version }}
              </option>
            </select>
          </td>
        </tr>
      </tbody>
    </table>
    <form class="grid" @submit.prevent="addPrinter">
      <label>
        Agent
        <select v-model="printerForm.agent_id" required>
          <option value="" disabled>Choose…</option>
          <option v-for="a in agents" :key="a.id" :value="a.id">
            {{ a.name }}
          </option>
        </select>
      </label>
      <label>Printer name <input v-model="printerForm.name" required /></label>
      <label>Model <input v-model="printerForm.model" /></label>
      <button>Add printer</button>
    </form>
  </section>

  <section class="card">
    <h2>Electricity tariffs</h2>
    <ul>
      <li v-for="t in tariffs" :key="t.id">
        {{ t.currency }} {{ t.rate_per_kwh }} /kWh from
        {{ dateTime(t.effective_from) }}
      </li>
    </ul>
    <form class="grid" @submit.prevent="addTariff">
      <label
        >Currency
        <input v-model="tariffForm.currency" required pattern="[A-Z]{3}"
      /></label>
      <label
        >Rate per kWh
        <input v-model="tariffForm.rate" required inputmode="decimal"
      /></label>
      <label
        >Effective from
        <input v-model="tariffForm.from" type="datetime-local" required
      /></label>
      <button>Add tariff</button>
    </form>
    <p class="muted small">
      Tariffs are effective-dated: add a new rate when your price changes. Past
      prints keep the rate that applied to them until you recalculate.
    </p>
  </section>

  <section class="card">
    <h2>Power profiles</h2>
    <ul>
      <li v-for="p in profiles" :key="p.id">
        {{ p.name }} v{{ p.version }} —
        <strong>{{
          p.calibrated_against_meter ? "meter-calibrated" : "estimated"
        }}</strong>
      </li>
    </ul>
    <form class="grid" @submit.prevent="addProfile">
      <label>Name <input v-model="profileForm.name" required /></label>
      <label
        >Version
        <input
          v-model.number="profileForm.version"
          type="number"
          min="1"
          required
      /></label>
      <label
        >Bed heater (W)
        <input v-model.number="profileForm.bedW" type="number" step="any"
      /></label>
      <label>
        Hotend heater (W)
        <input v-model.number="profileForm.hotendW" type="number" step="any" />
      </label>
      <label>
        Base load (W)
        <input
          v-model.number="profileForm.baseLoadW"
          type="number"
          step="any"
        />
      </label>
      <label>
        Outside-PSU load (W)
        <input
          v-model.number="profileForm.externalAcW"
          type="number"
          step="any"
        />
      </label>
      <label>
        PSU rating (W)
        <input
          v-model.number="profileForm.psuRatedW"
          type="number"
          step="any"
        />
      </label>
      <label
        >PSU efficiency (load:efficiency) <input v-model="profileForm.curve"
      /></label>
      <label
        >Fans (Klipper name: watts) <input v-model="profileForm.fans"
      /></label>
      <label class="inline">
        <input v-model="profileForm.calibrated" type="checkbox" /> Calibrated
        against a wall meter
      </label>
      <button>Add profile</button>
    </form>
    <p class="muted small">
      Profiles are immutable: to change a value, add a new version so past
      results stay reproducible.
    </p>
  </section>
</template>
