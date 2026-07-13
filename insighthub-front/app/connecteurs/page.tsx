"use client";

import { useState } from "react";
import PageHeader from "../components/PageHeader";
import { api, SyncResponse } from "../../lib/api";

interface Connector {
  id: string;
  source: string;
  label: string;
  icon: string;
  description: string;
  color: string;
}

const CONNECTORS: Connector[] = [
  {
    id: "jira",
    source: "jira",
    label: "Jira",
    icon: "J",
    description: "Issues, tickets, sprints et projets Jira",
    color: "#0052cc",
  },
  {
    id: "confluence",
    source: "confluence",
    label: "Confluence",
    icon: "C",
    description: "Pages, espaces et documentation Confluence",
    color: "#0065ff",
  },
  {
    id: "sharepoint",
    source: "sharepoint",
    label: "SharePoint",
    icon: "S",
    description: "Documents et listes SharePoint / Office 365",
    color: "#038387",
  },
];

interface SyncState {
  status: "idle" | "loading" | "success" | "error";
  result?: SyncResponse;
  error?: string;
}

export default function ConnecteursPage() {
  const [syncStates, setSyncStates] = useState<Record<string, SyncState>>(
    Object.fromEntries(CONNECTORS.map((c) => [c.id, { status: "idle" }]))
  );

  async function handleSync(connector: Connector) {
    setSyncStates((prev) => ({
      ...prev,
      [connector.id]: { status: "loading" },
    }));

    try {
      const result = await api.post<SyncResponse>(
        `/ingestion/${connector.source}/sync`,
        {}
      );
      setSyncStates((prev) => ({
        ...prev,
        [connector.id]: { status: "success", result },
      }));
    } catch (err) {
      setSyncStates((prev) => ({
        ...prev,
        [connector.id]: { status: "error", error: (err as Error).message },
      }));
    }
  }

  return (
    <>
      <PageHeader
        title="Connecteurs"
        subtitle="Gérez et synchronisez vos sources de données"
      />

      <div className="page-content">
        <div className="connectors-grid">
          {CONNECTORS.map((connector) => {
            const state = syncStates[connector.id];
            return (
              <div key={connector.id} className="card connector-card">
                {/* En-tête connecteur */}
                <div className="connector-header">
                  <div
                    className="connector-icon"
                    style={{ background: connector.color }}
                  >
                    {connector.icon}
                  </div>
                  <div>
                    <p className="connector-label">{connector.label}</p>
                    <p className="connector-desc">{connector.description}</p>
                  </div>
                  <div
                    className="connector-status-dot"
                    title="Configuré"
                  />
                </div>

                {/* Résultat de sync */}
                {state.status === "success" && state.result && (
                  <div className="sync-result success">
                    <p>✅ Synchronisation réussie</p>
                    <div className="sync-stats">
                      <span>{state.result.total_fetched} récupérés</span>
                      <span>{state.result.documents_processed} traités</span>
                      <span>{state.result.chunks_created} chunks</span>
                    </div>
                  </div>
                )}
                {state.status === "error" && (
                  <div className="sync-result error">
                    <p>❌ {state.error}</p>
                  </div>
                )}

                {/* Bouton sync */}
                <button
                  id={`sync-${connector.id}-btn`}
                  className="btn-primary connector-sync-btn"
                  onClick={() => handleSync(connector)}
                  disabled={state.status === "loading"}
                >
                  {state.status === "loading" ? (
                    <>⟳ Synchronisation en cours…</>
                  ) : (
                    <>↻ Synchroniser</>
                  )}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
