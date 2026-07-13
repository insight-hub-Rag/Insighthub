import PageHeader from "../components/PageHeader";

const QUERIES = [
  { id: "Q-001", question: "Quels tickets Jira sont bloqués ?", user: "Yassine A.", source: "jira", latency: 432, conf: "91%", date: "13/07/2026 20:12" },
  { id: "Q-002", question: "Résume IHUB-Architecture Confluence", user: "Yassine A.", source: "confluence", latency: 611, conf: "88%", date: "13/07/2026 20:00" },
  { id: "Q-003", question: "Documents SharePoint de ce mois", user: "Admin", source: "sharepoint", latency: 289, conf: "79%", date: "13/07/2026 19:45" },
  { id: "Q-004", question: "Combien d'incidents ServiceNow ouverts ?", user: "Yassine A.", source: "sql", latency: 180, conf: "95%", date: "13/07/2026 18:30" },
  { id: "Q-005", question: "Sprint actuel de l'équipe backend ?", user: "Admin", source: "jira", latency: 520, conf: "83%", date: "13/07/2026 17:10" },
];

export default function RequetesPage() {
  return (
    <>
      <PageHeader
        title="Requêtes & usage"
        subtitle="Historique de toutes les questions posées à l'assistant"
      />

      <div className="page-content">
        {/* Métriques rapides */}
        <div className="kpi-grid" style={{ gridTemplateColumns: "repeat(3,1fr)" }}>
          {[
            { label: "Total requêtes", value: "1 284" },
            { label: "Latence moyenne", value: "412 ms" },
            { label: "Confiance moyenne", value: "87%" },
          ].map((k) => (
            <div key={k.label} className="card kpi-card">
              <p className="kpi-label">{k.label}</p>
              <p className="kpi-value">{k.value}</p>
            </div>
          ))}
        </div>

        {/* Tableau */}
        <div className="card">
          <p className="section-title">Journal des requêtes</p>
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Question</th>
                <th>Utilisateur</th>
                <th>Source</th>
                <th>Latence</th>
                <th>Confiance</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {QUERIES.map((row) => (
                <tr key={row.id}>
                  <td><code style={{ fontSize: "11px" }}>{row.id}</code></td>
                  <td className="query-text">{row.question}</td>
                  <td>{row.user}</td>
                  <td><span className={`source-badge ${row.source}`}>{row.source}</span></td>
                  <td>{row.latency} ms</td>
                  <td className="conf-cell">{row.conf}</td>
                  <td className="date-cell">{row.date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
