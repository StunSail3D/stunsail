<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import CardGrid from "../components/CardGrid.vue";
import { request, messageOf, type LedgerEntry, type Spool } from "../api";
import { MATERIAL_DENSITY, dateTime, grams, money } from "../format";

const spools = ref<Spool[]>([]);
const error = ref("");
const ledgerFor = ref<string | null>(null);
const ledger = ref<LedgerEntry[]>([]);
const editing = ref<string | null>(null);
const edit = reactive({
  name: "",
  brand: "",
  colour: "",
  cost: "",
  currency: "",
});
const adjust = reactive({ spool: "", delta: "", notes: "" });

const blank = () => ({
  name: "",
  material: "PETG",
  brand: "",
  colour: "",
  diameter_mm: "1.75",
  density_g_cm3: MATERIAL_DENSITY["PETG"],
  opening_weight_g: "1000",
  purchase_cost: "",
  currency: "ZAR",
});
const form = reactive(blank());

function pickMaterial() {
  const density = MATERIAL_DENSITY[form.material];
  if (density) form.density_g_cm3 = density;
}

async function load() {
  try {
    spools.value = await request<Spool[]>("/spools?limit=200");
    error.value = "";
  } catch (e) {
    error.value = messageOf(e);
  }
}

async function guarded(action: () => Promise<unknown>) {
  try {
    await action();
    error.value = "";
    await load();
  } catch (e) {
    error.value = messageOf(e);
  }
}

const create = () =>
  guarded(async () => {
    const hasCost = form.purchase_cost !== "";
    await request("/spools", "POST", {
      name: form.name,
      material: form.material,
      brand: form.brand || null,
      colour: form.colour || null,
      diameter_mm: form.diameter_mm,
      density_g_cm3: form.density_g_cm3,
      opening_weight_g: form.opening_weight_g,
      purchase_cost: hasCost ? form.purchase_cost : null,
      currency: hasCost ? form.currency : null,
    });
    Object.assign(form, blank());
  });

function startEdit(spool: Spool) {
  editing.value = spool.id;
  Object.assign(edit, {
    name: spool.name,
    brand: spool.brand ?? "",
    colour: spool.colour ?? "",
    cost: spool.purchase_cost ?? "",
    currency: spool.currency ?? "ZAR",
  });
}

const saveEdit = (spool: Spool) =>
  guarded(async () => {
    const body: Record<string, unknown> = {
      name: edit.name,
      brand: edit.brand || null,
      colour: edit.colour || null,
    };
    if (edit.cost !== "") {
      body.purchase_cost = edit.cost;
      body.currency = edit.currency;
    }
    await request(`/spools/${spool.id}`, "PATCH", body);
    editing.value = null;
  });

const setStatus = (spool: Spool, status: string) =>
  guarded(() => request(`/spools/${spool.id}`, "PATCH", { status }));

async function showLedger(spool: Spool) {
  if (ledgerFor.value === spool.id) {
    ledgerFor.value = null;
    return;
  }
  try {
    ledger.value = await request<LedgerEntry[]>(
      `/spools/${spool.id}/ledger?limit=200`,
    );
    ledgerFor.value = spool.id;
  } catch (e) {
    error.value = messageOf(e);
  }
}

const applyAdjustment = () =>
  guarded(async () => {
    await request(`/spools/${adjust.spool}/adjustments`, "POST", {
      weight_delta_g: adjust.delta,
      notes: adjust.notes,
    });
    adjust.spool = "";
    adjust.delta = "";
    adjust.notes = "";
  });

onMounted(load);
</script>

<template>
  <h1>Spools</h1>
  <p v-if="error" class="error" role="alert">{{ error }}</p>

  <CardGrid
    page="spools"
    :cards="[{ id: 'add', title: 'Add a spool', height: 18 }]"
  >
    <template #add
      ><section>
        <h2>Add a spool</h2>
        <form class="grid" @submit.prevent="create">
          <label
            >Name <input v-model="form.name" required maxlength="200"
          /></label>
          <label>
            Material
            <input
              v-model="form.material"
              list="materials"
              required
              @change="pickMaterial"
            />
            <datalist id="materials">
              <option
                v-for="(_, name) in MATERIAL_DENSITY"
                :key="name"
                :value="name"
              />
            </datalist>
          </label>
          <label>Brand <input v-model="form.brand" /></label>
          <label>Colour <input v-model="form.colour" /></label>
          <label
            >Diameter (mm)
            <input v-model="form.diameter_mm" required inputmode="decimal"
          /></label>
          <label>
            Density (g/cm³)
            <input v-model="form.density_g_cm3" required inputmode="decimal" />
          </label>
          <label>
            Filament weight (g)
            <input
              v-model="form.opening_weight_g"
              required
              inputmode="decimal"
            />
          </label>
          <label
            >Price paid <input v-model="form.purchase_cost" inputmode="decimal"
          /></label>
          <label
            >Currency
            <input v-model="form.currency" maxlength="3" pattern="[A-Z]{3}"
          /></label>
          <button>Add spool</button>
        </form>
        <p class="muted small">
          Weight is net filament weight (without the empty spool). Leave the
          price empty to skip filament cost.
        </p>
      </section></template
    >
  </CardGrid>

  <p v-if="!spools.length" class="empty">No spools yet.</p>
  <table v-else>
    <thead>
      <tr>
        <th>Spool</th>
        <th>Material</th>
        <th>Remaining</th>
        <th>Price</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      <template v-for="spool in spools" :key="spool.id">
        <tr :class="{ archived: spool.status === 'archived' }">
          <template v-if="editing === spool.id">
            <td colspan="4">
              <form class="grid" @submit.prevent="saveEdit(spool)">
                <label>Name <input v-model="edit.name" required /></label>
                <label>Brand <input v-model="edit.brand" /></label>
                <label>Colour <input v-model="edit.colour" /></label>
                <label
                  >Price <input v-model="edit.cost" inputmode="decimal"
                /></label>
                <label
                  >Currency <input v-model="edit.currency" maxlength="3"
                /></label>
                <button>Save</button>
                <button type="button" @click="editing = null">Cancel</button>
              </form>
              <p class="muted small">
                A new price applies to future prints only.
              </p>
            </td>
          </template>
          <template v-else>
            <td>
              {{ spool.name }}
              <small class="muted">{{
                [spool.brand, spool.colour].filter(Boolean).join(" · ")
              }}</small>
            </td>
            <td>{{ spool.material }}</td>
            <td>
              {{ grams(spool.remaining_g) }}
              <small>of {{ grams(spool.opening_weight_g) }}</small>
            </td>
            <td>{{ money(spool.purchase_cost, spool.currency) }}</td>
          </template>
          <td class="actions">
            <button @click="startEdit(spool)">Edit</button>
            <button @click="showLedger(spool)">History</button>
            <button @click="adjust.spool = spool.id">Adjust</button>
            <button
              v-if="spool.status === 'active'"
              @click="setStatus(spool, 'archived')"
            >
              Archive
            </button>
            <button v-else @click="setStatus(spool, 'active')">Restore</button>
          </td>
        </tr>
        <tr v-if="adjust.spool === spool.id">
          <td colspan="5">
            <form class="grid" @submit.prevent="applyAdjustment">
              <label>
                Change (g, negative to remove)
                <input v-model="adjust.delta" required inputmode="decimal" />
              </label>
              <label
                >Reason <input v-model="adjust.notes" required maxlength="500"
              /></label>
              <button>Record adjustment</button>
              <button type="button" @click="adjust.spool = ''">Cancel</button>
            </form>
          </td>
        </tr>
        <tr v-if="ledgerFor === spool.id">
          <td colspan="5">
            <table class="sub">
              <tbody>
                <tr v-for="entry in ledger" :key="entry.id">
                  <td>{{ dateTime(entry.occurred_at) }}</td>
                  <td>{{ entry.movement_type }}</td>
                  <td class="num">{{ grams(entry.weight_delta_g) }}</td>
                  <td>{{ entry.notes }}</td>
                </tr>
              </tbody>
            </table>
          </td>
        </tr>
      </template>
    </tbody>
  </table>
</template>
