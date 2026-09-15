import Link from "next/link";

const nav = [
  { href: "/", label: "Home" },
  { href: "/api-providers", label: "API Providers" },
  { href: "/models", label: "Models" },
  { href: "/credits", label: "Free Credits" },
  { href: "/compare", label: "Compare" },
  { href: "/cheap-flagships", label: "Cheap flagships" },
  { href: "/changes", label: "Changes" },
  { href: "/submit", label: "Submit" },
];

export function SiteHeader() {
  return (
    <header className="site-header">
      <div className="site-header-inner">
        <Link href="/" className="brand">
          <span className="brand-mark">●</span>
          <span className="brand-name">OpenRadar</span>
        </Link>
        <nav className="site-nav">
          {nav.map((n) => (
            <Link key={n.href} href={n.href} className="nav-link">
              {n.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
