"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const navItems = [
  { href: "/", label: "Dashboard", icon: "H" },
  { href: "/requests", label: "Requests", icon: "R" },
  { href: "/orders", label: "Service Orders", icon: "O" },
  { href: "#", label: "Customers", icon: "C" },
  { href: "#", label: "Reports", icon: "B" },
  { href: "#", label: "Settings", icon: "S" }
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="logo">A</span>
          <span>Traviz</span>
        </div>
        <nav className="nav" aria-label="Support navigation">
          {navItems.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            if (item.href === "#") {
              return (
                <button className="navItem" type="button" key={item.label}>
                  <span>{item.icon}</span>
                  {item.label}
                </button>
              );
            }

            return (
              <Link className={`navItem ${active ? "active" : ""}`} href={item.href} key={item.href}>
                <span>{item.icon}</span>
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="sidebarScript">Travel connects People</div>
        <div className="helpBox">
          <strong>Need Help?</strong>
          <span>Contact support team or check our guides.</span>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <div className="searchBox">
            <span>S</span>
            <input placeholder="Search by name, phone, request ID or service type..." />
          </div>
          <div className="profile">
            <div className="avatar">SC</div>
            <div>
              <strong>Sagar Choudhary</strong>
              <span>Support Agent</span>
            </div>
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}
