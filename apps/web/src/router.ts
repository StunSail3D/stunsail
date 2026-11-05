import { createRouter, createWebHashHistory } from "vue-router";
import DashboardView from "./views/DashboardView.vue";
import JobsView from "./views/JobsView.vue";
import JobDetailView from "./views/JobDetailView.vue";
import SpoolsView from "./views/SpoolsView.vue";
import ReportsView from "./views/ReportsView.vue";
import SettingsView from "./views/SettingsView.vue";

// Hash history keeps the built app servable as plain static files by the API.
export const routes = [
  { path: "/", name: "dashboard", component: DashboardView },
  { path: "/jobs", name: "jobs", component: JobsView },
  { path: "/jobs/:id", name: "job", component: JobDetailView, props: true },
  { path: "/spools", name: "spools", component: SpoolsView },
  { path: "/reports", name: "reports", component: ReportsView },
  { path: "/settings", name: "settings", component: SettingsView },
];

export const makeRouter = () =>
  createRouter({ history: createWebHashHistory(), routes });
