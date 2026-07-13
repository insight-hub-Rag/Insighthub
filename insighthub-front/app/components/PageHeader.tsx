"use client";

import React from "react";

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  /** Optional badge/info shown next to title (e.g. project selector) */
  badge?: React.ReactNode;
  /** Primary CTA button label */
  actionLabel?: string;
  actionId?: string;
  onAction?: () => void;
  /** Right slot for extra controls (e.g. date filter) */
  extra?: React.ReactNode;
}

export default function PageHeader({
  title,
  subtitle,
  badge,
  actionLabel,
  actionId,
  onAction,
  extra,
}: PageHeaderProps) {
  return (
    <header className="page-header">
      <div className="page-header-left">
        <div className="page-header-title-row">
          <h1 className="page-header-title">{title}</h1>
          {badge && <span className="page-header-badge">{badge}</span>}
        </div>
        {subtitle && <p className="page-header-subtitle">{subtitle}</p>}
      </div>
      <div className="page-header-right">
        {extra}
        {actionLabel && (
          <button
            id={actionId ?? "page-header-action-btn"}
            className="btn-primary"
            onClick={onAction}
          >
            {actionLabel}
          </button>
        )}
      </div>
    </header>
  );
}
