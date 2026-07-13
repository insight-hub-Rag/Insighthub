export default function AppFooter() {
  return (
    <footer className="site-footer">
      <span>© {new Date().getFullYear()} InsightHub — Plateforme de connaissance unifiee</span>
      <nav className="footer-links" aria-label="Liens du pied de page">
        <a href="/securite">Securite</a>
        <a href="/requetes">Requetes &amp; usage</a>
        <a href="mailto:support@insighthub.io">Support</a>
      </nav>
    </footer>
  );
}
