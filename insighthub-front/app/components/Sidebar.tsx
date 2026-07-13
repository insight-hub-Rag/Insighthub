"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// Icons (inline SVG)
function IconGrid() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" />
      <rect x="14" y="14" width="7" height="7" /><rect x="3" y="14" width="7" height="7" />
    </svg>
  );
}
function IconUsers() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  );
}
function IconPlug() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22V12" /><path d="M5 12H2a10 10 0 0 0 20 0h-3" />
      <rect x="8" y="2" width="2" height="6" rx="1" /><rect x="14" y="2" width="2" height="6" rx="1" />
    </svg>
  );
}
function IconActivity() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
    </svg>
  );
}
function IconShield() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  );
}
function IconChat() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  );
}

interface NavItem {
  label: string;
  href: string;
  icon: React.ReactNode;
}
interface NavSection {
  title: string;
  items: NavItem[];
}

const adminNav: NavSection[] = [
  {
    title: "VUE D'ENSEMBLE",
    items: [
      { label: "Dashboard global", href: "/dashboard", icon: <IconGrid /> },
      { label: "Utilisateurs", href: "/utilisateurs", icon: <IconUsers /> },
    ],
  },
  {
    title: "PLATEFORME",
    items: [
      { label: "Connecteurs", href: "/connecteurs", icon: <IconPlug /> },
      { label: "Requetes & usage", href: "/requetes", icon: <IconActivity /> },
      { label: "Securite & acces", href: "/securite", icon: <IconShield /> },
    ],
  },
  {
    title: "ESPACE",
    items: [
      { label: "Assistant (chat)", href: "/chat", icon: <IconChat /> },
    ],
  },
];

function NavLink({ item }: { item: NavItem }) {
  const pathname = usePathname();
  const active = pathname === item.href || pathname.startsWith(item.href + "/");
  return (
    <Link href={item.href} className={`sidebar-nav-link${active ? " active" : ""}`}>
      <span className="sidebar-nav-icon">{item.icon}</span>
      <span>{item.label}</span>
    </Link>
  );
}

interface SidebarProps {
  user?: { initials: string; name: string; role: string };
}
const defaultUser = { initials: "YA", name: "Yassine A.", role: "Administrateur" };

export default function Sidebar({ user = defaultUser }: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <span className="sidebar-logo-icon">IH</span>
        <span className="sidebar-logo-text">InsightHub</span>
      </div>
      <nav className="sidebar-nav">
        {adminNav.map((section) => (
          <div key={section.title} className="sidebar-section">
            <p className="sidebar-section-title">{section.title}</p>
            <ul className="sidebar-section-list">
              {section.items.map((item) => (
                <li key={item.href}>
                  <NavLink item={item} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
      <div className="sidebar-footer">
        <div className="sidebar-user-avatar" aria-label={user.name}>{user.initials}</div>
        <div className="sidebar-user-info">
          <span className="sidebar-user-name">{user.name}</span>
          <span className="sidebar-user-role">{user.role}</span>
        </div>
      </div>
    </aside>
  );
}
