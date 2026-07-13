/**
 * Client API centralisé pour InsightHub.
 * Lit NEXT_PUBLIC_API_URL pour pointer vers le backend FastAPI.
 * Usage : import { api } from "@/lib/api"
 */

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

type FetchOptions = RequestInit & {
  /** Ajouter des query params sous forme d'objet */
  params?: Record<string, string | number | boolean>;
};

async function request<T>(
  path: string,
  options: FetchOptions = {}
): Promise<T> {
  const { params, ...init } = options;

  // Construction de l'URL avec query params si fournis
  let url = `${BASE_URL}${path}`;
  if (params) {
    const qs = new URLSearchParams(
      Object.entries(params).map(([k, v]) => [k, String(v)])
    );
    url += `?${qs.toString()}`;
  }

  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...init.headers,
    },
    ...init,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail ?? `Erreur ${response.status}`);
  }

  // 204 No Content
  if (response.status === 204) return undefined as T;

  return response.json() as Promise<T>;
}

// ── Helpers HTTP ────────────────────────────────────────────────────────────

export const api = {
  get: <T>(path: string, options?: FetchOptions) =>
    request<T>(path, { ...options, method: "GET" }),

  post: <T>(path: string, body?: unknown, options?: FetchOptions) =>
    request<T>(path, {
      ...options,
      method: "POST",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),

  put: <T>(path: string, body?: unknown, options?: FetchOptions) =>
    request<T>(path, {
      ...options,
      method: "PUT",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),

  patch: <T>(path: string, body?: unknown, options?: FetchOptions) =>
    request<T>(path, {
      ...options,
      method: "PATCH",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),

  delete: <T>(path: string, options?: FetchOptions) =>
    request<T>(path, { ...options, method: "DELETE" }),
};

// ── Types réponses backend ───────────────────────────────────────────────────

export interface SearchResponse {
  question: string;
  answer: string;
  model: string;
  sources: Array<{
    source_type: string;
    document_id: string;
    title: string;
    content: string;
  }>;
  total_chunks_searched: number;
  performance: { total_ms: number };
}

export interface SyncResponse {
  status: string;
  source: string;
  documents_processed: number;
  chunks_created: number;
  total_fetched: number;
}

export interface HealthResponse {
  status: string;
}
