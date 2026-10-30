export type Mode = "blur" | "collapse" | "hide";
export type Settings = { mode: Mode; enabled: boolean };
export const DEFAULT_SETTINGS: Settings = { mode: "blur", enabled: true };

export function normalizeSettings(raw: Record<string, unknown>): Settings {
  return {
    mode: raw.mode === "collapse" || raw.mode === "hide" ? raw.mode : "blur",
    enabled: typeof raw.enabled === "boolean" ? raw.enabled : true,
  };
}

// Register first and discard stale reads if a live update arrives during startup.
export function watchSettings(onUpdate: (settings: Settings) => void): void {
  let current = { ...DEFAULT_SETTINGS };
  let revision = 0;
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "sync" || !("mode" in changes || "enabled" in changes)) return;
    revision++;
    current = normalizeSettings({
      mode: "mode" in changes ? changes.mode.newValue : current.mode,
      enabled: "enabled" in changes ? changes.enabled.newValue : current.enabled,
    });
    onUpdate(current);
  });
  const initialRevision = revision;
  void chrome.storage.sync.get(["mode", "enabled"]).then((stored) => {
    if (revision !== initialRevision) return;
    current = normalizeSettings(stored);
    onUpdate(current);
  }).catch(() => onUpdate(current));
}
