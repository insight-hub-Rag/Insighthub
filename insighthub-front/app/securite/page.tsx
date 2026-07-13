import PageHeader from "../components/PageHeader";

const PERMISSIONS = [
  { role: "Administrateur", chat: true, connectors: true, users: true, queries: true, security: true },
  { role: "Utilisateur", chat: true, connectors: false, users: false, queries: false, security: false },
];

function Check({ ok }: { ok: boolean }) {
  return (
    <span style={{ color: ok ? "var(--green)" : "var(--red)", fontWeight: 600 }}>
      {ok ? "✓" : "✗"}
    </span>
  );
}

export default function SecuritePage() {
  return (
    <>
      <PageHeader
        title="Sécurité & accès"
        subtitle="Rôles, permissions et configuration de sécurité"
      />

      <div className="page-content">
        {/* Matrice des permissions */}
        <div className="card">
          <p className="section-title">Matrice des permissions par rôle</p>
          <table className="data-table">
            <thead>
              <tr>
                <th>Rôle</th>
                <th style={{ textAlign: "center" }}>Assistant (chat)</th>
                <th style={{ textAlign: "center" }}>Connecteurs</th>
                <th style={{ textAlign: "center" }}>Utilisateurs</th>
                <th style={{ textAlign: "center" }}>Requêtes</th>
                <th style={{ textAlign: "center" }}>Sécurité</th>
              </tr>
            </thead>
            <tbody>
              {PERMISSIONS.map((row) => (
                <tr key={row.role}>
                  <td>
                    <span className={`role-badge ${row.role === "Administrateur" ? "admin" : "user"}`}>
                      {row.role}
                    </span>
                  </td>
                  <td style={{ textAlign: "center" }}><Check ok={row.chat} /></td>
                  <td style={{ textAlign: "center" }}><Check ok={row.connectors} /></td>
                  <td style={{ textAlign: "center" }}><Check ok={row.users} /></td>
                  <td style={{ textAlign: "center" }}><Check ok={row.queries} /></td>
                  <td style={{ textAlign: "center" }}><Check ok={row.security} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Infos sécurité */}
        <div className="security-info-grid">
          <div className="card">
            <p className="section-title">Authentification</p>
            <div className="security-item">
              <span className="status-dot green" />
              <span>JWT — Access token (15 min) + Refresh token (7 jours)</span>
            </div>
            <div className="security-item">
              <span className="status-dot green" />
              <span>Mots de passe hashés avec bcrypt</span>
            </div>
            <div className="security-item">
              <span className="status-dot green" />
              <span>CORS restreint à localhost:3000</span>
            </div>
          </div>

          <div className="card">
            <p className="section-title">Base de données</p>
            <div className="security-item">
              <span className="status-dot green" />
              <span>PostgreSQL 16 + pgvector</span>
            </div>
            <div className="security-item">
              <span className="status-dot green" />
              <span>Connexion interne Docker uniquement</span>
            </div>
            <div className="security-item">
              <span className="status-dot orange" />
              <span>Chiffrement credentials connecteurs — à venir</span>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
