// Supplied by build.mjs; the default targets the local Compose API.
declare const __ANTISLOP_API_BASE_URL__: string;
export const BLOCKLIST_URL = `${__ANTISLOP_API_BASE_URL__}/v1/blocklist`;
export const SYNC_ALARM = "antislop-blocklist-sync";
export const SYNC_PERIOD_MINUTES = 60;
export const CACHE_KEY = "blocklistCache";
