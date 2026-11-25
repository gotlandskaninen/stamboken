import { fetchApi } from "@/lib/api";

export async function codeLoginEnabled() {
  return fetchApi<{ enabled: boolean }>("/v2/login/status", {
    forceProd: true,
    timeout: 2500,
  })
    .then((status) => status.enabled === true)
    .catch(() => false);
}
