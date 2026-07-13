import PageHeader from "../components/PageHeader";

const USERS = [
  { initials: "YA", name: "Yassine A.", email: "yassine@insighthub.io", role: "Administrateur", status: "actif", joined: "01/06/2026" },
  { initials: "MA", name: "Mohamed A.", email: "mohamed@insighthub.io", role: "Utilisateur", status: "actif", joined: "15/06/2026" },
  { initials: "SC", name: "Sara C.", email: "sara@insighthub.io", role: "Utilisateur", status: "actif", joined: "20/06/2026" },
  { initials: "KL", name: "Karim L.", email: "karim@insighthub.io", role: "Utilisateur", status: "inactif", joined: "05/07/2026" },
];

export default function UtilisateursPage() {
  return (
    <>
      <PageHeader
        title="Utilisateurs"
        subtitle="Gestion des comptes et des rôles"
        actionLabel="+ Inviter un utilisateur"
        actionId="invite-user-btn"
      />

      <div className="page-content">
        <div className="card">
          <p className="section-title">{USERS.length} utilisateurs</p>
          <table className="data-table">
            <thead>
              <tr>
                <th>Utilisateur</th>
                <th>Email</th>
                <th>Rôle</th>
                <th>Statut</th>
                <th>Membre depuis</th>
              </tr>
            </thead>
            <tbody>
              {USERS.map((u) => (
                <tr key={u.email}>
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                      <div className="user-avatar">{u.initials}</div>
                      <span style={{ fontWeight: 500 }}>{u.name}</span>
                    </div>
                  </td>
                  <td className="date-cell">{u.email}</td>
                  <td>
                    <span className={`role-badge ${u.role === "Administrateur" ? "admin" : "user"}`}>
                      {u.role}
                    </span>
                  </td>
                  <td>
                    <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                      <span className={`status-dot ${u.status === "actif" ? "green" : "orange"}`} />
                      {u.status}
                    </span>
                  </td>
                  <td className="date-cell">{u.joined}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
