import { createApp } from "vue";
import { afterEach, describe, expect, it } from "vitest";
import App from "./App.vue";

describe("App foundation", () => {
  let mountedApp: ReturnType<typeof createApp> | undefined;

  afterEach(() => {
    mountedApp?.unmount();
    mountedApp = undefined;
    document.body.innerHTML = "";
  });

  it("identifies the project and next milestone", () => {
    const container = document.createElement("div");
    document.body.append(container);
    mountedApp = createApp(App);
    mountedApp.mount(container);

    expect(container.querySelector("h1")?.textContent).toBe("StunSail");
    expect(container.textContent).toContain("printer integration is next");
  });
});
