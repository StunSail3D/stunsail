import { createApp, type App as VueApp } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.vue";
import { authRequired, setToken } from "./api";
import { currencyError, currencySettings } from "./currency";
import { routes } from "./router";

type Handler = (url: string, init?: RequestInit) => unknown;
let handlers: Record<string, Handler> = {};
let calls: { url: string; method: string; body?: string }[] = [];
let mounted: VueApp | undefined;

const settle = async () => {
  for (let i = 0; i < 6; i++)
    await new Promise((resolve) => setTimeout(resolve, 0));
};

async function open(path: string): Promise<HTMLElement> {
  const router = createRouter({ history: createMemoryHistory(), routes });
  await router.push(path);
  const root = document.createElement("div");
  document.body.append(root);
  mounted = createApp(App).use(router);
  mounted.mount(root);
  await settle();
  return root;
}

beforeEach(() => {
  handlers = {};
  calls = [];
  localStorage.clear();
  authRequired.value = false;
  currencySettings.value = null;
  currencyError.value = "";
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      calls.push({
        url,
        method: init?.method ?? "GET",
        body: init?.body as string | undefined,
      });
      const key = Object.keys(handlers).find((k) =>
        url.split("?")[0].endsWith(k),
      );
      if (!key && url.endsWith("/settings/currency"))
        return new Response(JSON.stringify({ currency: "ZAR", symbol: "R" }), {
          status: 200,
        });
      if (!key)
        return new Response(
          JSON.stringify({ error: { code: "x", message: `no ${url}` } }),
          { status: 404 },
        );
      const result = handlers[key](url, init);
      if (result instanceof Response) return result;
      return new Response(JSON.stringify(result), { status: 200 });
    }),
  );
});

afterEach(() => {
  mounted?.unmount();
  mounted = undefined;
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

const summary = {
  currency: "ZAR",
  mixed_currencies: false,
  jobs: 0,
  jobs_without_cost: 0,
  kwh: "0",
  filament_g: "0",
  electricity_cost: "0",
  filament_cost: "0",
  total_cost: "0",
  by_month: [],
};

describe("filament and currency settings", () => {
  it("filters materials and colours, opens information, and submits the shared currency", async () => {
    handlers = { "/spools": () => [] };
    const root = await open("/spools");
    const form = root.querySelector<HTMLFormElement>("form.grid")!;
    const selects = form.querySelectorAll<HTMLSelectElement>("select");
    const material = selects[0];
    const colour = selects[1];
    expect(
      material.querySelector<HTMLOptionElement>('option[value="PLA"]')
        ?.disabled,
    ).toBe(false);
    expect(
      material.querySelector<HTMLOptionElement>('option[value="ASA"]')
        ?.disabled,
    ).toBe(true);
    expect(
      material.querySelector<HTMLOptionElement>('option[value="PLA Silk"]')
        ?.disabled,
    ).toBe(false);
    expect(
      material.querySelector<HTMLOptionElement>('option[value="PLA Stone"]')
        ?.disabled,
    ).toBe(true);
    colour.value = "White";
    colour.dispatchEvent(new Event("change"));
    material.value = "PLA Silk";
    material.dispatchEvent(new Event("change"));
    await settle();
    expect(colour.value).toBe("");
    colour.value = "White";
    colour.dispatchEvent(new Event("change"));
    const price = Array.from(form.querySelectorAll("label"))
      .find((label) => label.textContent?.includes("Price paid"))!
      .querySelector("input")!;
    expect(price.closest(".currency-input")?.textContent).toContain("R");
    price.value = "250";
    price.dispatchEvent(new Event("input"));
    const dialog = root.querySelector<HTMLDialogElement>("dialog")!;
    dialog.showModal = vi.fn();
    root
      .querySelector<HTMLButtonElement>('[aria-label="Filament information"]')!
      .click();
    expect(dialog.showModal).toHaveBeenCalledOnce();
    form.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
    await settle();
    const posted = calls.find(
      (call) => call.url.endsWith("/spools") && call.method === "POST",
    )!;
    expect(JSON.parse(posted.body!)).toMatchObject({
      name: "PLA Silk White",
      material: "PLA Silk",
      colour: "White",
      purchase_cost: "250",
      currency: "ZAR",
    });
  });

  it("saves a custom currency symbol and uses the currency for new tariffs", async () => {
    handlers = {
      "/agents": () => [],
      "/printers": () => [],
      "/calibration-profiles": () => [],
      "/tariffs": () => [],
      "/settings/currency": (_url, init) =>
        init?.method === "PUT"
          ? JSON.parse(init.body as string)
          : { currency: "ZAR", symbol: "R" },
    };
    const root = await open("/settings");
    const currencyForm = Array.from(
      root.querySelectorAll<HTMLFormElement>("form"),
    ).find((form) => form.textContent?.includes("Save currency"))!;
    const select = currencyForm.querySelector("select")!;
    select.value = "USD";
    select.dispatchEvent(new Event("change"));
    await settle();
    const symbol = currencyForm.querySelector("input")!;
    symbol.value = "US$";
    symbol.dispatchEvent(new Event("input"));
    currencyForm.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
    await settle();
    expect(currencySettings.value).toEqual({ currency: "USD", symbol: "US$" });
    const tariff = Array.from(
      root.querySelectorAll<HTMLFormElement>("form"),
    ).find((form) => form.textContent?.includes("Add tariff"))!;
    const rate = tariff.querySelector("input")!;
    expect(rate.closest(".currency-input")?.textContent).toContain("US$");
    expect(tariff.textContent).not.toContain("Currency:");
    rate.value = "1.25";
    rate.dispatchEvent(new Event("input"));
    tariff.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
    await settle();
    const posted = calls.find(
      (call) => call.url.endsWith("/tariffs") && call.method === "POST",
    )!;
    expect(JSON.parse(posted.body!).currency).toBe("USD");
  });

  it("edits a legacy spool using its original material and currency", async () => {
    const spool = {
      id: "s1",
      name: "Old silk",
      material: "Silk PLA",
      brand: null,
      colour: "White",
      diameter_mm: "1.75",
      density_g_cm3: "1.24",
      opening_weight_g: "1000",
      remaining_g: "500",
      purchase_cost: "12",
      currency: "USD",
      status: "active",
    };
    handlers = { "/spools": () => [spool], "/spools/s1": () => spool };
    const root = await open("/spools");
    Array.from(root.querySelectorAll("button"))
      .find((button) => button.textContent === "Edit")!
      .click();
    await settle();
    const form = Array.from(
      root.querySelectorAll<HTMLFormElement>("form"),
    ).find((item) => item.textContent?.includes("Cancel"))!;
    expect(
      form
        .querySelector<HTMLSelectElement>("select")
        ?.querySelector('option[value="White"]'),
    ).not.toBeNull();
    expect(form.querySelector(".currency-input")?.textContent).toContain("USD");
    form.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
    await settle();
    const patched = calls.find(
      (call) => call.url.endsWith("/spools/s1") && call.method === "PATCH",
    )!;
    expect(JSON.parse(patched.body!)).toMatchObject({
      currency: "USD",
      colour: "White",
    });
  });
});

describe("dashboard", () => {
  it("collapses and expands the icon navigation without losing link labels", async () => {
    handlers = {
      "/printers": () => [],
      "/jobs": () => [],
      "/reports/summary": () => summary,
    };
    const root = await open("/");
    const toggle = root.querySelector<HTMLButtonElement>(".menu-toggle")!;
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const icon = toggle.querySelector("img");
    expect(icon?.getAttribute("src")).toBe("/logo_icon.svg");
    expect(root.querySelector(".brand-name")?.textContent).toBe("StunSail");
    expect(
      root.querySelector('nav a[aria-label="Settings"]')?.className,
    ).toContain("settings-link");
    toggle.click();
    await settle();
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(toggle.querySelector("img")).toBe(icon);
    expect(root.querySelector(".brand-name")).toBeNull();
    expect(root.querySelector('nav a[aria-label="Settings"]')).not.toBeNull();
    toggle.click();
    await settle();
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
  });

  it("closes the mobile overlay after navigation, backdrop click, or Escape", async () => {
    vi.stubGlobal("innerWidth", 390);
    handlers = {
      "/printers": () => [],
      "/jobs": () => [],
      "/reports/summary": () => summary,
      "/agents": () => [],
      "/calibration-profiles": () => [],
      "/tariffs": () => [],
    };
    const root = await open("/");
    const toggle = root.querySelector<HTMLButtonElement>(".menu-toggle")!;
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    toggle.click();
    await settle();
    expect(root.querySelector(".menu-backdrop")).not.toBeNull();
    root.querySelector<HTMLButtonElement>(".menu-backdrop")!.click();
    await settle();
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    toggle.click();
    await settle();
    root
      .querySelector<HTMLElement>(".app-shell")!
      .dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      );
    await settle();
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    toggle.click();
    await settle();
    root
      .querySelector<HTMLAnchorElement>('nav a[aria-label="Settings"]')!
      .click();
    await settle();
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(root.textContent).toContain("Settings");
  });

  it("resets the saved dashboard layout for the current screen size", async () => {
    handlers = {
      "/printers": () => [
        {
          id: "p1",
          agent_id: "a",
          name: "Ender",
          calibration_profile_id: null,
        },
      ],
      "/live": () => ({ printer_id: "p1", sample_observed_at: null }),
      "/jobs": () => [],
      "/reports/summary": () => summary,
    };
    const columns =
      window.innerWidth >= 1200 ? 3 : window.innerWidth >= 768 ? 2 : 1;
    const key = `stunsail-layout-v1:dashboard:${columns}`;
    localStorage.setItem(
      key,
      JSON.stringify([{ i: "printer-p1", x: 0, y: 0, w: 1, h: 12 }]),
    );
    const root = await open("/");
    expect(localStorage.getItem(key)).not.toBeNull();
    const reset = Array.from(root.querySelectorAll("button")).find(
      (button) => button.textContent === "Reset layout",
    )!;
    reset.click();
    await settle();
    expect(localStorage.getItem(key)).toBeNull();
    expect(root.textContent).toContain("Ender");
  });

  it("guides first-time users to Settings when no printer exists", async () => {
    handlers = {
      "/printers": () => [],
      "/jobs": () => [],
      "/reports/summary": () => summary,
    };
    const root = await open("/");
    expect(root.textContent).toContain("No printer yet");
  });

  it("shows live temperatures, progress and warns when data is stale", async () => {
    const job = {
      id: "j1",
      filename: "cube.gcode",
      state: "printing",
      started_at: "2026-11-05T10:00:00Z",
    };
    handlers = {
      "/printers": () => [
        {
          id: "p1",
          agent_id: "a",
          name: "Ender",
          calibration_profile_id: null,
        },
      ],
      "/live": () => ({
        printer_id: "p1",
        sample_observed_at: "2026-11-05T10:00:00Z",
        sample_age_s: 120,
        status: {
          extruder: { temperature: 215.2, target: 215 },
          heater_bed: { temperature: 70, target: 70 },
          virtual_sdcard: { progress: 0.42 },
          print_stats: { print_duration: 300 },
        },
        active_job: job,
      }),
      "/jobs": () => [],
      "/reports/summary": () => summary,
    };
    const root = await open("/");
    expect(root.textContent).toContain("cube.gcode");
    expect(root.textContent).toContain("215.2 °C");
    expect(root.textContent).toContain("42%");
    expect(root.querySelector("[data-test=stale]")?.textContent).toContain(
      "may be offline",
    );
  });
});

describe("job detail", () => {
  const detail = {
    id: "j1",
    filename: "cube.gcode",
    state: "completed",
    started_at: "2026-11-05T10:00:00Z",
    duration_s: 464,
    finalised_at: "2026-11-05T10:08:00Z",
    spool_id: null,
    energy: {
      revision: 1,
      kwh: "0.0172",
      covered_s: 82,
      uncovered_s: 18,
      invalid_samples: 0,
      basis: "estimated",
      profile_version: 2,
    },
    costs: [
      {
        kind: "electricity",
        currency: "ZAR",
        amount: "0.0775",
        details: {
          lines: [{ rate_per_kwh: "4.5", kwh: 0.0172, cost: "0.0775" }],
        },
      },
      {
        kind: "filament",
        currency: "ZAR",
        amount: "3.10",
        details: { mass_g: "7.8" },
      },
    ],
    total_cost: "3.1775",
    total_cost_currency: "ZAR",
  };

  it("labels estimated energy, flags low coverage and shows the breakdown", async () => {
    handlers = { "/jobs/j1": () => detail, "/spools": () => [] };
    const root = await open("/jobs/j1");
    expect(root.textContent).toContain("Estimated (not meter-calibrated)");
    expect(root.textContent).toContain("profile v2");
    expect(root.querySelector("[data-test=coverage]")?.className).toContain(
      "warn",
    );
    expect(root.textContent).toContain("R 3.18");
    expect(root.textContent).toContain("7.8 g");
  });

  it("assigns a spool through the API", async () => {
    handlers = {
      "/jobs/j1": () => detail,
      "/jobs/j1/spool": () => ({ ...detail, spool_id: "s1" }),
      "/spools": () => [
        {
          id: "s1",
          name: "PETG grey",
          material: "PETG",
          status: "active",
          remaining_g: "900",
        },
      ],
    };
    const root = await open("/jobs/j1");
    const select = root.querySelector("select") as HTMLSelectElement;
    select.value = "s1";
    select.dispatchEvent(new Event("change"));
    await settle();
    root.querySelector("form")!.dispatchEvent(new Event("submit"));
    await settle();
    const post = calls.find((c) => c.url.endsWith("/jobs/j1/spool"));
    expect(post?.method).toBe("POST");
    expect(JSON.parse(post!.body!)).toEqual({ spool_id: "s1" });
  });
});

describe("authentication", () => {
  it("sends the saved admin token and flags a 401", async () => {
    setToken("secret-token-123456");
    handlers = {
      "/jobs": () =>
        new Response(
          JSON.stringify({
            error: { code: "unauthorized", message: "admin token required" },
          }),
          { status: 401 },
        ),
    };
    const root = await open("/jobs");
    expect(authRequired.value).toBe(true);
    expect(root.textContent).toContain("requires an admin token");
    expect(root.textContent).toContain("admin token required");
  });
});

describe("settings", () => {
  it("only allows unassigned Agents when adding a printer", async () => {
    handlers = {
      "/agents": () => [
        { id: "a", name: "Assigned", revoked: false },
        { id: "b", name: "Available", revoked: false },
      ],
      "/printers": () => [
        {
          id: "p",
          name: "Printer",
          agent_id: "a",
          calibration_profile_id: null,
        },
      ],
      "/calibration-profiles": () => [],
      "/tariffs": () => [],
    };
    const root = await open("/settings");
    const form = Array.from(
      root.querySelectorAll<HTMLFormElement>("form"),
    ).find((item) => item.textContent?.includes("Add printer"))!;
    expect(
      form.querySelector<HTMLOptionElement>('option[value="a"]')?.disabled,
    ).toBe(true);
    expect(
      form.querySelector<HTMLOptionElement>('option[value="b"]')?.disabled,
    ).toBe(false);
  });
  it("confirms revocation and shows the Agent as revoked", async () => {
    let revoked = false;
    handlers = {
      "/agents": () => [
        { id: "ender", name: "Ender", last_sync_at: null, revoked },
      ],
      "/agents/ender/revoke": () => {
        revoked = true;
        return { id: "ender", name: "Ender", last_sync_at: null, revoked };
      },
      "/printers": () => [],
      "/calibration-profiles": () => [],
      "/tariffs": () => [],
    };
    vi.spyOn(window, "confirm")
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);
    const root = await open("/settings");
    const button = root.querySelector<HTMLButtonElement>(
      '[aria-label="Revoke access for Ender (ender)"]',
    )!;
    button.click();
    await settle();
    expect(calls.filter((call) => call.url.endsWith("/revoke"))).toHaveLength(
      0,
    );
    button.click();
    await settle();
    expect(calls.filter((call) => call.url.endsWith("/revoke"))).toHaveLength(
      1,
    );
    expect(root.textContent).toContain("Revoked");
    expect(
      root.querySelector('[aria-label="Revoke access for Ender (ender)"]'),
    ).toBeNull();
    expect(
      root.querySelector('[aria-label="Reset token for Ender (ender)"]'),
    ).not.toBeNull();
  });

  it("confirms a token reset, displays the replacement, and permits dismissal", async () => {
    handlers = {
      "/agents": () => [{ id: "ender", name: "Ender", last_sync_at: null }],
      "/agents/ender/reset-token": () => ({
        agent_id: "ender",
        token: "new-token",
      }),
      "/printers": () => [],
      "/calibration-profiles": () => [],
      "/tariffs": () => [],
    };
    const confirm = vi
      .spyOn(window, "confirm")
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);
    const root = await open("/settings");
    const button = root.querySelector<HTMLButtonElement>(
      '[aria-label="Reset token for Ender (ender)"]',
    )!;
    button.click();
    await settle();
    expect(calls.filter((c) => c.url.endsWith("/reset-token"))).toHaveLength(0);
    button.click();
    await settle();
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(calls.filter((c) => c.url.endsWith("/reset-token"))).toEqual([
      expect.objectContaining({ method: "POST" }),
    ]);
    expect(
      root.querySelector("[data-test=agent-token]")?.textContent,
    ).toContain("new-token");
    (
      root.querySelector("[data-test=agent-token] button") as HTMLButtonElement
    ).click();
    await settle();
    expect(root.querySelector("[data-test=agent-token]")).toBeNull();
    confirm.mockRestore();
  });

  it("shows a new agent token once after registering", async () => {
    handlers = {
      "/agents": (_url, init) =>
        init?.method === "POST" ? { agent_id: "ender", token: "tok-abc" } : [],
      "/printers": () => [],
      "/calibration-profiles": () => [],
      "/tariffs": () => [],
    };
    const root = await open("/settings");
    const form = Array.from(
      root.querySelectorAll<HTMLFormElement>("form.grid"),
    ).find((item) => item.textContent?.includes("Register agent"))!;
    const inputs = form.querySelectorAll("input");
    inputs[0].value = "ender";
    inputs[0].dispatchEvent(new Event("input"));
    inputs[1].value = "Ender";
    inputs[1].dispatchEvent(new Event("input"));
    form.dispatchEvent(new Event("submit"));
    await settle();
    expect(
      root.querySelector("[data-test=agent-token]")?.textContent,
    ).toContain("tok-abc");
  });
});
