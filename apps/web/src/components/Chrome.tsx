import { useEffect, type ReactNode } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';

/**
 * Chrome shared by every route.
 *
 * `Link` and `NavLink` rather than `<a href>` for the internal links so
 * navigation is a client-side transition and the router can keep focus
 * management — a page swap that does not move focus or announce itself is
 * worse for a screen reader than a full load.
 */

/**
 * The router does not scroll for us. Without this, moving from the knowledge
 * base to `/#download` changes the URL and leaves the visitor halfway down a
 * different page — a link that appears to do nothing.
 */
function HashScroller() {
  const { pathname, hash } = useLocation();

  useEffect(() => {
    if (!hash) {
      window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
      return;
    }

    const target = document.getElementById(decodeURIComponent(hash.slice(1)));
    if (!target) return;

    // The effect runs after the commit, so the target has a box to scroll to.
    target.scrollIntoView();
  }, [pathname, hash]);

  return null;
}

export function Header() {
  return (
    <header className="site-header">
      <div className="wrap header-inner">
        <Link className="brand" to="/">
          <img src="./assets/logo-512.png" alt="" width={36} height={36} />
          <span>BarberShop</span>
        </Link>
        <nav aria-label="Main">
          <Link className="header-extra" to="/#features">
            What it does
          </Link>
          <Link className="header-extra" to="/#how">
            How it works
          </Link>
          <NavLink to="/knowledge">Knowledge base</NavLink>
          <Link className="button button-small" to="/#download">
            Get the app
          </Link>
        </nav>
      </div>
    </header>
  );
}

export function Footer() {
  const year = new Date().getFullYear();

  return (
    <footer className="site-footer">
      <div className="wrap footer-grid">
        <div className="footer-brand">
          <Link className="brand" to="/">
            <img src="./assets/logo-512.png" alt="" width={32} height={32} />
            <span>BarberShop</span>
          </Link>
          <p className="muted">
            One app for the people in the chair and the people who put them there.
          </p>
        </div>

        <nav aria-label="Product">
          <h2>Product</h2>
          <Link to="/#features">What it does</Link>
          <Link to="/#how">How it works</Link>
          <Link to="/#download">Download</Link>
        </nav>

        <nav aria-label="Support">
          <h2>Support</h2>
          <Link to="/knowledge">Knowledge base</Link>
          <Link to="/knowledge#booking">Booking help</Link>
          <Link to="/knowledge#provider">Provider help</Link>
          <Link to="/knowledge#privacy">Privacy</Link>
        </nav>
      </div>

      <div className="wrap footer-bottom">
        <p>© {year} BarberShop</p>
        <p>Free for customers · Providers pay 1% of completed bookings</p>
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
      <HashScroller />
      <Header />
      <main id="main">{children}</main>
      <Footer />
    </>
  );
}
