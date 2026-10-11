import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { GROUPS, allEntries, groupsFor, searchEntries } from '@/content/knowledge';
import Knowledge from '@/routes/Knowledge';

describe('the content itself', () => {
  it('has entries at all', () => {
    expect(allEntries().length).toBeGreaterThan(30);
  });

  it('gives every group and section an id so links land', () => {
    // A knowledge base whose contents page scrolls nowhere is worse than none.
    for (const group of GROUPS) {
      expect(group.id).toMatch(/^[a-z0-9-]+$/);
      for (const section of group.sections) {
        expect(section.id).toMatch(/^[a-z0-9-]+$/);
      }
    }
  });

  it('has no duplicate ids', () => {
    const ids = allEntries().map((item) => item.entry.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('gives every entry a question and a real answer', () => {
    for (const { entry } of allEntries()) {
      expect(entry.question.length).toBeGreaterThan(5);
      expect(entry.answer.length).toBeGreaterThan(30);
    }
  });

  it('never promises a feature that does not exist', () => {
    // Anything not shipped has to say so. A knowledge base that documents the
    // roadmap in the present tense is worse than having none.
    const shipped = /not yet|on the roadmap/i;
    const dishonest = allEntries().filter(
      ({ entry }) =>
        /(you can|currently|we now|supports)/i.test(entry.answer) &&
        /(reschedul|waitlist|saved shop|staff member)/i.test(entry.answer) &&
        !shipped.test(entry.answer),
    );
    expect(dishonest.map((item) => item.entry.id)).toEqual([]);
  });
});

describe('search', () => {
  it('finds an answer by its question', () => {
    expect(searchEntries('refund')[0]?.entry.id).toBe('refund-how');
  });

  it('finds an answer by a word someone would type', () => {
    // Nobody searching for a refund types "reimbursement process".
    const results = searchEntries('money back').map((item) => item.entry.id);
    expect(results).toContain('refund-how');
  });

  it('finds a no-show by how it is phrased', () => {
    expect(searchEntries('did not turn up')[0]?.entry.id).toBe('no-show-fee');
  });

  it('ranks a title match above a passing mention', () => {
    const results = searchEntries('deposit');
    expect(results[0]?.entry.question.toLowerCase()).toContain('deposit');
  });

  it('returns nothing for a blank query', () => {
    expect(searchEntries('   ')).toEqual([]);
  });

  it('returns nothing rather than everything for a nonsense query', () => {
    expect(searchEntries('quantum tunnelling')).toEqual([]);
  });
});

describe('audience filter', () => {
  it('hides provider-only content from customers', () => {
    const customerGroups = groupsFor('customers');
    expect(customerGroups.some((group) => group.id === 'provider')).toBe(false);
    expect(customerGroups.some((group) => group.id === 'booking')).toBe(true);
  });

  it('keeps shared sections for everyone', () => {
    const providerGroups = groupsFor('providers');
    expect(providerGroups.some((group) => group.id === 'account')).toBe(true);
  });
});

describe('the page', () => {
  function renderPage() {
    return render(
      <MemoryRouter>
        <Knowledge />
      </MemoryRouter>,
    );
  }

  it('lists the contents', () => {
    renderPage();
    expect(screen.getByRole('heading', { level: 1, name: 'Knowledge base' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Running a shop on BarberShop' })).toHaveAttribute(
      'href',
      '#provider',
    );
    // The contents page reaches the sections, not just the chapters.
    expect(screen.getByRole('link', { name: 'Getting paid' })).toHaveAttribute(
      'href',
      '#getting-paid',
    );
  });

  it('answers a search and counts what it found', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByRole('searchbox'), 'withdraw');
    expect(screen.getByText(/answers for “withdraw”/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'How do I withdraw my earnings?' })).toBeInTheDocument();
  });

  it('says so when a search finds nothing', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByRole('searchbox'), 'zzzznothing');
    expect(screen.getByText(/Nothing matched/)).toBeInTheDocument();
  });

  it('filters to providers', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: 'For providers' }));

    expect(screen.getByRole('heading', { name: 'Getting paid' })).toBeInTheDocument();
    // Customer-only sections are gone, not merely hidden behind a filter chip.
    expect(screen.queryByRole('heading', { name: 'Booking an appointment' })).not.toBeInTheDocument();
  });

  it('marks the active filter for assistive tech', async () => {
    const user = userEvent.setup();
    renderPage();

    const providers = screen.getByRole('button', { name: 'For providers' });
    expect(providers).toHaveAttribute('aria-pressed', 'false');
    await user.click(providers);
    expect(providers).toHaveAttribute('aria-pressed', 'true');
  });

  it('returns to everything', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: 'For providers' }));
    await user.click(screen.getByRole('button', { name: 'Everyone' }));
    expect(screen.getByRole('heading', { name: 'Booking an appointment' })).toBeInTheDocument();
  });
});