<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import CardGrid from "../components/CardGrid.vue";
import { request, messageOf, type LedgerEntry, type Spool } from "../api";
import { MATERIAL_DENSITY, dateTime, grams, money } from "../format";
import { currencySettings, currencySymbol } from "../currency";
import { coloursFor, freeMaterials, materials, reelImage } from "../filaments";

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
});
const adjust = reactive({ spool: "", delta: "", notes: "" });

const blank = () => ({
  material: "PLA",
  brand: "",
  colour: "",
  diameter_mm: "1.75",
  density_g_cm3: MATERIAL_DENSITY["PLA"],
  opening_weight_g: "1000",
  purchase_cost: "",
});
const form = reactive(blank());
const availableColours = computed(() => coloursFor(form.material));
const infoDialog = ref<HTMLDialogElement | null>(null);
const infoMaterial = ref("PLA");
const selectedInfo = computed(() =>
  materials.find((item) => item.name === infoMaterial.value),
);

function pickMaterial() {
  const density =
    MATERIAL_DENSITY[form.material] ??
    (form.material.startsWith("PLA ") ? MATERIAL_DENSITY.PLA : undefined);
  if (density) form.density_g_cm3 = density;
  form.colour = "";
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
    const currency = currencySettings.value;
    if (hasCost && !currency)
      throw new Error("Currency settings are not loaded.");
    await request("/spools", "POST", {
      name: [form.material, form.colour].filter(Boolean).join(" "),
      material: form.material,
      brand: form.brand || null,
      colour: form.colour || null,
      diameter_mm: form.diameter_mm,
      density_g_cm3: form.density_g_cm3,
      opening_weight_g: form.opening_weight_g,
      purchase_cost: hasCost ? form.purchase_cost : null,
      currency: hasCost && currency ? currency.currency : null,
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
      const currency = spool.currency ?? currencySettings.value?.currency;
      if (!currency) throw new Error("Currency settings are not loaded.");
      body.purchase_cost = edit.cost;
      body.currency = currency;
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
        <div class="section-heading">
          <h2>Add a spool</h2>
          <button
            type="button"
            class="info-button"
            aria-label="Filament information"
            @click="infoDialog?.showModal()"
          >
            ⓘ
          </button>
        </div>
        <form class="grid" @submit.prevent="create">
          <label>
            Material
            <select v-model="form.material" required @change="pickMaterial">
              <option
                v-for="material in materials"
                :key="material.name"
                :value="material.name"
                :disabled="!freeMaterials.has(material.name)"
              >
                {{ material.name
                }}{{ freeMaterials.has(material.name) ? "" : " — Pro👑" }}
              </option>
            </select>
          </label>
          <label>Brand <input v-model="form.brand" /></label>
          <label
            >Colour
            <select v-model="form.colour" required>
              <option value="" disabled>Choose a colour…</option>
              <option
                v-for="colour in availableColours"
                :key="colour.colour"
                :value="colour.colour"
              >
                {{ colour.colour }} ({{ colour.availability }})
              </option>
            </select>
          </label>
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
            >Price paid
            <span class="currency-input">
              <span>{{ currencySettings?.symbol ?? "—" }}</span>
              <input v-model="form.purchase_cost" inputmode="decimal" />
            </span>
          </label>
          <button :disabled="!currencySettings">Add spool</button>
        </form>
        <p class="muted small">
          Weight is net filament weight (without the empty spool). Leave the
          price empty to skip filament cost.
        </p>
      </section></template
    >
  </CardGrid>

  <dialog
    ref="infoDialog"
    class="filament-dialog"
    aria-labelledby="filament-info-title"
  >
    <div class="section-heading">
      <h2 id="filament-info-title">Filament information</h2>
      <button type="button" @click="infoDialog?.close()">Close</button>
    </div>
    <p class="muted small">
      General reference only; follow the filament manufacturer's
      recommendations. Split variants share the reference information of their
      source type.
    </p>
    <label
      >Filament type
      <select v-model="infoMaterial">
        <option
          v-for="material in materials"
          :key="material.name"
          :value="material.name"
        >
          {{ material.name }}
        </option>
      </select>
    </label>
    <dl v-if="selectedInfo" class="filament-properties">
      <template v-for="(value, label) in selectedInfo.properties" :key="label">
        <dt>{{ label }}</dt>
        <dd>{{ value }}</dd>
      </template>
    </dl>
  </dialog>

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
                <label
                  >Colour
                  <select v-model="edit.colour">
                    <option value="">Not specified</option>
                    <option
                      v-if="
                        edit.colour &&
                        !coloursFor(spool.material).some(
                          (item) => item.colour === edit.colour,
                        )
                      "
                      :value="edit.colour"
                    >
                      {{ edit.colour }} (existing)
                    </option>
                    <option
                      v-for="colour in coloursFor(spool.material)"
                      :key="colour.colour"
                      :value="colour.colour"
                    >
                      {{ colour.colour }} ({{ colour.availability }})
                    </option>
                  </select>
                </label>
                <label
                  >Price
                  <span class="currency-input">
                    <span>{{
                      currencySymbol(
                        spool.currency ?? currencySettings?.currency,
                      ) || "—"
                    }}</span>
                    <input v-model="edit.cost" inputmode="decimal" />
                  </span>
                </label>
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
              <img
                v-if="reelImage(spool.colour)"
                :src="reelImage(spool.colour)!"
                :alt="`${spool.colour} filament spool`"
                class="spool-image"
              />
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
