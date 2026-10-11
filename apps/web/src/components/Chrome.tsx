import type { ReactNode } from 'react';
import { Link, NavLink } from 'react-router-dom';

/**
 * Chrome shared by every route.
 *
 * `NavLink` rather than `<a href>` for the internal links so navigation is a
 * client-side transition and the router can keep focus management — a page
 * swap that does not move focus or announce itself is worse for a screen
 * reader than a full load.
 */
export function Header() {
  return (
    <header className="site-header">
      <div className="wrap header-inner">
        <Link className="brand" to="/">
          <img src="./assets/logo-512.png" alt="" width={36} height={36} />
          <span>BarberShop</span>
        </Link>
        <nav aria-label="Main">
          <NavLink to="/" end>
            Home
          </NavLink>
          <NavLink to="/knowledge">Knowledge base</NavLink>
          <Link className="button button-small" to="/knowledge#providers">
            For providers
          </Link>
        </nav>
      </div>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="site-footer">
      <div className="wrap footer-inner">
        <p className="muted">BarberShop — one app for customers and providers.</p>
        <nav aria-label="Footer">
          <Link to="/knowledge">Knowledge base</Link>
          <a href="../docs/ARCHITECTURE.md">Architecture</a>
          <a href="../docs/DEVELOPMENT.md">Development</a>
          <a href="../services/api/docs/">API</a>
        </nav>
      </div>
    </footer>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <Header />
      <main id="main">{children}</main>
      <Footer />
    </>
  );
}