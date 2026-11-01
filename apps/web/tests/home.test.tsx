import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import App from '@/App';
import { GROUPS, allEntries } from '@/content/knowledge';

function renderAt(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe('the marketing page', () => {
  it('says what the app is and who it is for', () => {
    renderAt();

    expect(
      screen.getByRole('heading', { level: 1, name: /Book the chair\. Run the shop\./ }),
    ).toBeInTheDocument();
    expect(screen.getByText(/for people who want a haircut and the people who give one/i)).toBeInTheDocument();
    expect(screen.getByText('For customers')).toBeInTheDocument();
    expect(screen.getByText('For providers')).toBeInTheDocument();
  });

  it('explains how booking works', () => {
    renderAt();

    expect(screen.getByRole('heading', { name: 'How booking works' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Download the app' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Pick a slot and book' })).toBeInTheDocument();
  });

  it('offers the app from the hero and the download section', () => {
    renderAt();

    const downloadLinks = screen.getAllByRole('link', { name: 'Get the app' });
    expect(downloadLinks.length).toBeGreaterThanOrEqual(2);
    for (const link of downloadLinks) {
      expect(link).toHaveAttribute('href', '/#download');
    }
  });

  it('links to the knowledge base in the main navigation', () => {
    renderAt();

    const mainNav = within(screen.getByRole('navigation', { name: 'Main' }));
    expect(mainNav.getByRole('link', { name: 'Knowledge base' })).toHaveAttribute(
      'href',
      '/knowledge',
    );
  });

  it('sends popular questions to the answer that actually exists', () => {
    renderAt();

    const deposit = screen.getByRole('link', { name: /Why is there a deposit\?/ });
    expect(deposit).toHaveAttribute('href', '/knowledge#deposits');

    const ids = new Set([
      ...GROUPS.map((group) => group.id),
      ...GROUPS.flatMap((group) => group.sections.map((section) => section.id)),
      ...allEntries().map(({ entry }) => entry.id),
    ]);
    for (const link of screen.getAllByRole('link')) {
      const href = link.getAttribute('href') ?? '';
      const hash = href.startsWith('/knowledge#') ? href.slice('/knowledge#'.length) : null;
      if (hash) expect(ids.has(hash)).toBe(true);
    }
  });

  it('opens the store listings in a new tab', () => {
    renderAt();

    const ios = screen.getByRole('link', { name: /App Store/ });
    expect(ios).toHaveAttribute('href', 'https://apps.apple.com/us/search?term=BarberShop');
    expect(ios).toHaveAttribute('target', '_blank');
    expect(ios.getAttribute('rel')).toContain('noopener');

    const android = screen.getByRole('link', { name: /Google Play/ });
    expect(android).toHaveAttribute(
      'href',
      'https://play.google.com/store/apps/details?id=com.barbershop.app',
    );
    expect(android).toHaveAttribute('target', '_blank');
  });
});

describe('the footer', () => {
  it('links to pages and anchors that exist', () => {
    renderAt();

    const footer = screen.getByRole('contentinfo');

    // Every internal link is either the home page, an on-page anchor, or the
    // knowledge base. No relative links into files that are not deployed.
    for (const link of within(footer).getAllByRole('link')) {
      const href = link.getAttribute('href') ?? '';
      expect(href).not.toMatch(/\.\.\//);
      expect(href).toMatch(
        /^(\/(#[\w-]+)?|\/knowledge(#[\w-]+)?|https:\/\/(apps\.apple\.com|play\.google\.com)\/)/,
      );
    }
  });

  it('does not bring back the documentation links that were never served', () => {
    renderAt();

    const footer = screen.getByRole('contentinfo');
    expect(within(footer).queryByRole('link', { name: 'Architecture' })).not.toBeInTheDocument();
    expect(within(footer).queryByRole('link', { name: 'Development' })).not.toBeInTheDocument();
    expect(within(footer).queryByRole('link', { name: /^API$/ })).not.toBeInTheDocument();
  });

  it('only deep-links to knowledge base sections that exist', () => {
    renderAt();

    const ids = new Set([
      ...GROUPS.map((group) => group.id),
      ...GROUPS.flatMap((group) => group.sections.map((section) => section.id)),
      ...allEntries().map(({ entry }) => entry.id),
    ]);

    const footer = screen.getByRole('contentinfo');
    for (const link of within(footer).getAllByRole('link')) {
      const href = link.getAttribute('href') ?? '';
      const marker = '/knowledge#';
      if (!href.startsWith(marker)) continue;
      expect(ids.has(href.slice(marker.length))).toBe(true);
    }
  });
});
