export interface RetrievalScope {
  paths: string[];
  folders: string[];
  note_types: string[];
  tags: string[];
  sources: string[];
  date_from?: string;
  date_to?: string;
  excluded_paths: string[];
  pinned_paths: string[];
  include_graph: boolean;
  allow_protected: boolean;
  saved_scope?: string;
}

export interface RankingComponents {
  exact: number;
  lexical: number;
  semantic: number;
  metadata: number;
  link: number;
  graph: number;
  rerank: number;
  total: number;
}

export interface ConversationEvidence {
  evidence_id: string;
  path: string;
  heading?: string;
  start_line: number;
  end_line: number;
  source_hash: string;
  chunk_hash: string;
  excerpt: string;
  ranking: RankingComponents;
  support: "direct" | "synthesis" | "inference";
  stale: boolean;
}

export interface ConversationParagraph {
  text: string;
  citations: string[];
  support: "direct" | "synthesis" | "inference";
}

export interface ConversationTurn {
  turn_id: string;
  created_at: string;
  query: string;
  state: string;
  evidence: ConversationEvidence[];
  answer: ConversationParagraph[];
  explanation: string;
  provider_disclosure: Record<string, unknown>;
  diagnostics: string[];
}

export interface ConversationMetadata {
  type: "knowledge-conversation";
  conversation_schema: number;
  conversation_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  status: "active" | "archived";
  retrieval_scope: RetrievalScope;
  pinned_sources: string[];
  excluded_sources: string[];
  parent_conversation_id?: string;
  branch_from_turn_id?: string;
  turns?: null;
}

export interface ConversationArtifact {
  path: string;
  content_hash: string;
  metadata: ConversationMetadata;
  turns: ConversationTurn[];
  human_body: string;
}

export interface RetrievalResult {
  evidence_id: string;
  path: string;
  heading?: string;
  start_line: number;
  end_line: number;
  context_text: string;
  ranking: RankingComponents;
  scope_reason: string;
  duplicate_paths: string[];
}

export interface RetrievalResponse {
  query: string;
  results: RetrievalResult[];
  state: string;
  index_state: string;
  semantic_state: string;
  rerank_state: string;
  context_characters: number;
  scope: RetrievalScope;
  diagnostics: string[];
  provider_disclosure: Record<string, unknown>;
}

export interface IndexHealth {
  state: "missing" | "healthy" | "stale" | "building" | "interrupted" | "corrupt" | "incompatible";
  active_usable: boolean;
  schema_version?: number;
  documents: number;
  chunks: number;
  embeddings: number;
  stale_embeddings: number;
  missing_embeddings: number;
  stale_paths: string[];
  missing_paths: string[];
  orphaned_paths: string[];
  rebuild_status?: string;
  diagnostics: string[];
}

export interface ConversationProposalPreview {
  proposal_id: string;
  action: string;
  target_path: string;
  operation: string;
  base_hash?: string;
  unified_diff?: string;
  new_content?: string;
  evidence: Array<Record<string, unknown>>;
}

export interface ConversationProposalResult {
  proposal_id: string;
  proposal_path: string;
  preview: ConversationProposalPreview;
}

export const emptyScope = (): RetrievalScope => ({
  paths: [], folders: [], note_types: [], tags: [], sources: [], excluded_paths: [], pinned_paths: [],
  include_graph: true, allow_protected: false,
});
