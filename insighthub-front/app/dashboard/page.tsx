import PageHeader from "../components/PageHeader";

const KPIS = [
  { label: "Questions posées", value: "1 284", trend: "+12% vs semaine dernière", up: true },
  { label: "Confiance moyenne", value: "87%", trend: "+3 pts", up: true },
  { label: "Documents indexés", value: "42 910", trend: "+1 204 cette semaine", up: true },
  { label: "Utilisateurs actifs", value: "63", trend: "−2 vs semaine dernière", up: false },
];

const RECENT_QUERIES = [
  { q: "Quels tickets Jira sont en cours ?", source: "jira", date: "il y a 5 min", conf: "91%" },
  { q: "Résume la page Confluence IHUB-Arch", source: "confluence", date: "il y a 12 min", conf: "88%" },
  { q: "Documents SharePoint modifiés ce mois", source: "sharepoint", date: "il y a 1h", conf: "79%" },
  { q: "Combien d'incidents ServiceNow ouverts ?", source: "sql", date: "il y a 2h", conf: "95%" },
];

export default function DashboardPage() {
  return (
    <>
      <PageHeader
        title="Dashboard global"
        subtitle="Vue d'ensemble de l'activité de la plateforme — toutes sources confondues"
        actionLabel="+ Ajouter un connecteur"
        actionId="add-connector-btn"
        extra={
          <button id="date-filter-btn" className="btn-secondary">
            7 derniers jours ▾
          </button>
        }
      />

      <div className="page-content">
        {/* KPI row */}
        <div className="kpi-grid">
          {KPIS.map((kpi) => (
            <div key={kpi.label} className="card kpi-card">
              <p className="kpi-label">{kpi.label}</p>
              <p className="kpi-value">{kpi.value}</p>
              <p className="kpi-trend" style={{ color: kpi.up ? "var(--green)" : "var(--red)" }}>
                {kpi.up ? "↑" : "↓"} {kpi.trend}
              </p>
            </div>
          ))}
        </div>

        {/* Dernières questions */}
        <div className="card">
          <p className="section-title">Dernières questions posées</p>
          <table className="data-table">
            <thead>
              <tr>
                <th>Question</th>
                <th>Source</th>
                <th>Confiance</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {RECENT_QUERIES.map((row, i) => (
                <tr key={i}>
                  <td className="query-text">{row.q}</td>
                  <td>
                    <span className={`source-badge ${row.source}`}>{row.source}</span>
                  </td>
                  <td className="conf-cell">{row.conf}</td>
                  <td className="date-cell">{row.date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Sources actives */}
        <div className="card">
          <p className="section-title">Sources actives</p>
          <div className="sources-status-grid">
            {[
              { name: "Jira", docs: "12 450", status: "ok" },
              { name: "Confluence", docs: "8 320", status: "ok" },
              { name: "SharePoint", docs: "22 140", status: "ok" },
              { name: "ServiceNow (SQL)", docs: "—", status: "warning" },
            ].map((s) => (
              <div key={s.name} className="source-status-item">
                <span className={`status-dot ${s.status === "ok" ? "green" : "orange"}`} />
                <span className="source-name">{s.name}</span>
                <span className="source-docs">{s.docs} docs</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
