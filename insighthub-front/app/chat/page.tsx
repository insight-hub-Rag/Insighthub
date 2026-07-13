"use client";

import { useState, useRef, useEffect } from "react";
import PageHeader from "../components/PageHeader";
import { api, SearchResponse } from "../../lib/api";

interface Message {
  id: string;
  role: "user" | "assistant";
  question?: string;
  answer?: string;
  sources?: SearchResponse["sources"];
  latency?: number;
  loading?: boolean;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend() {
    const q = input.trim();
    if (!q || sending) return;
    setInput("");
    setSending(true);

    const id = Date.now().toString();
    setMessages((prev) => [
      ...prev,
      { id, role: "user", question: q },
      { id: id + "-resp", role: "assistant", loading: true },
    ]);

    try {
      const data = await api.post<SearchResponse>("/search", { question: q });
      setMessages((prev) =>
        prev.map((m) =>
          m.id === id + "-resp"
            ? {
                ...m,
                loading: false,
                answer: data.answer,
                sources: data.sources,
                latency: data.performance.total_ms,
              }
            : m
        )
      );
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === id + "-resp"
            ? { ...m, loading: false, answer: "Erreur : " + (err as Error).message }
            : m
        )
      );
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Assistant IA"
        subtitle="Posez une question en langage naturel sur vos données (Jira, Confluence, SharePoint…)"
      />

      <div className="page-content" style={{ gap: 0, paddingBottom: 0, flex: 1 }}>
        {/* Zone de messages */}
        <div className="chat-messages">
          {messages.length === 0 && (
            <div className="chat-empty">
              <div className="chat-empty-icon">💬</div>
              <p className="chat-empty-title">Comment puis-je vous aider ?</p>
              <p className="chat-empty-sub">
                Essayez : « Quels sont les tickets Jira en cours ? »
              </p>
              <div className="chat-suggestions">
                {[
                  "Quels sont les tickets ouverts dans Jira ?",
                  "Résume les pages Confluence sur le projet IHUB",
                  "Quels documents SharePoint ont été modifiés récemment ?",
                ].map((s) => (
                  <button
                    key={s}
                    className="chat-suggestion-btn"
                    onClick={() => { setInput(s); }}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg) => (
            <div key={msg.id} className={`chat-bubble-row ${msg.role}`}>
              {msg.role === "user" ? (
                <div className="chat-bubble user">{msg.question}</div>
              ) : msg.loading ? (
                <div className="chat-bubble assistant loading">
                  <span className="dot" /><span className="dot" /><span className="dot" />
                </div>
              ) : (
                <div className="chat-bubble assistant">
                  <p className="chat-answer">{msg.answer}</p>
                  {msg.sources && msg.sources.length > 0 && (
                    <div className="chat-sources">
                      <p className="chat-sources-title">Sources utilisées :</p>
                      {msg.sources.map((s, i) => (
                        <div key={i} className="chat-source-item">
                          <span className={`source-badge ${s.source_type}`}>
                            {s.source_type}
                          </span>
                          <span className="source-title">{s.title || s.document_id}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {msg.latency !== undefined && (
                    <p className="chat-latency">⏱ {msg.latency} ms</p>
                  )}
                </div>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Barre de saisie */}
        <div className="chat-input-bar">
          <input
            id="chat-input"
            className="chat-input"
            type="text"
            placeholder="Posez votre question…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            disabled={sending}
            autoFocus
          />
          <button
            id="chat-send-btn"
            className="btn-primary chat-send-btn"
            onClick={handleSend}
            disabled={sending || !input.trim()}
          >
            {sending ? "…" : "Envoyer →"}
          </button>
        </div>
      </div>
    </>
  );
}
