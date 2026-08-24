import "server-only";

import { cookies } from "next/headers";

export type SourceStatus = "active" | "invalidated";
export type DocumentStatus = "indexed" | "invalidated";

export interface KnowledgeDocument {
  id: string;
  source_id: string;
  filename: string;
  media_type: string;
  byte_size: number;
  content_sha256: string;
  extraction_version: string;
  embedding_model: string;
  embedding_dimensions: number;
  character_count: number;
  chunk_count: number;
  metadata: Record<string, unknown>;
  status: DocumentStatus;
  revision: number;
  created_at: string;
  updated_at: string;
  invalidated_at: string | null;
  invalidation_reason: string | null;
}

export interface KnowledgeSource {
  id: string;
  business_id: string;
  source_type: "upload" | "reference";
  title: string;
  source_uri: string | null;
  metadata: Record<string, unknown>;
  status: SourceStatus;
  revision: number;
  created_at: string;
  updated_at: string;
  invalidated_at: string | null;
  invalidation_reason: string | null;
  documents: KnowledgeDocument[];
}

export interface KnowledgeDashboard {
  business_id: string;
  supported_file_types: string[];
  embedding_model: string;
  sources: KnowledgeSource[];
}

export interface KnowledgeSearchHit {
  score: number;
  text: string;
  citation: {
    source_id: string;
    source_title: string;
    source_uri: string | null;
    document_id: string;
    filename: string;
    document_content_sha256: string;
    document_created_at: string;
    chunk_id: string;
    chunk_ordinal: number;
    start_character: number;
    end_character: number;
    content_sha256: string;
  };
}

async function knowledgeGet(path: string): Promise<unknown | null> {
  const store = await cookies();
  const session = store.get("id")?.value;
  if (!session) return null;
  try {
    const base = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
    const response = await fetch(`${base}${path}`, {
      cache: "no-store",
      headers: { Cookie: `id=${session}` },
      signal: AbortSignal.timeout(5000),
    });
    return response.ok ? ((await response.json()) as unknown) : null;
  } catch {
    return null;
  }
}

export async function getKnowledgeDashboard(): Promise<KnowledgeDashboard | null> {
  const value = await knowledgeGet("/knowledge");
  if (typeof value !== "object" || value === null) return null;
  const item = value as Partial<KnowledgeDashboard>;
  return typeof item.business_id === "string" && Array.isArray(item.sources)
    ? (item as KnowledgeDashboard)
    : null;
}

export async function searchKnowledge(
  query: string,
): Promise<KnowledgeSearchHit[] | null> {
  const value = await knowledgeGet(
    `/knowledge/search?q=${encodeURIComponent(query)}`,
  );
  if (typeof value !== "object" || value === null) return null;
  const hits = (value as { hits?: unknown }).hits;
  return Array.isArray(hits) ? (hits as KnowledgeSearchHit[]) : null;
}
