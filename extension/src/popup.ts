import { normalizeSettings, watchSettings } from "./settings";
const enabled = document.getElementById("enabled") as HTMLInputElement;
const mode = document.getElementById("mode") as HTMLSelectElement;
const warning = document.getElementById("warning") as HTMLParagraphElement;
const status = document.getElementById("status") as HTMLParagraphElement;

watchSettings((settings) => {
  enabled.checked = settings.enabled;
  mode.value = settings.mode;
  warning.hidden = settings.mode !== "hide";
  enabled.disabled = false;
  mode.disabled = false;
});

async function save(): Promise<void> {
  const settings = normalizeSettings({ mode: mode.value, enabled: enabled.checked });
  warning.hidden = settings.mode !== "hide";
  enabled.disabled = true;
  mode.disabled = true;
  try {
    await chrome.storage.sync.set(settings);
    status.textContent = "Saved";
  } catch {
    status.textContent = "Could not save. Please try again.";
  } finally {
    enabled.disabled = false;
    mode.disabled = false;
  }
}
enabled.addEventListener("change", () => void save());
mode.addEventListener("change", () => void save());
