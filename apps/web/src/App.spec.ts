import { createApp, type App as VueApp } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.vue";
import { authRequired, setToken } from "./api";
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

describe("dashboard", () => {
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
    expect(root.textContent).toContain("ZAR 3.18");
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
    const inputs = root
      .querySelectorAll<HTMLInputElement>("form.grid")[0]
      .querySelectorAll("input");
    inputs[0].value = "ender";
    inputs[0].dispatchEvent(new Event("input"));
    inputs[1].value = "Ender";
    inputs[1].dispatchEvent(new Event("input"));
    root.querySelectorAll("form.grid")[0].dispatchEvent(new Event("submit"));
    await settle();
    expect(
      root.querySelector("[data-test=agent-token]")?.textContent,
    ).toContain("tok-abc");
  });
});
