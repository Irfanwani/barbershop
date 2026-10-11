import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import App from '@/App';
import { PriceCard, ShopCard, ShopList } from '@/components/Cards';
import type { PriceBand, Provider } from '@/lib/types';

const band: PriceBand = {
  service_type: 'haircut',
  service_type_label: 'Haircut',
  median: 25000,
  median_display: '₹250.00',
  minimum_display: '₹200.00',
  maximum_display: '₹400.00',
  p25_display: '₹220.00',
  p75_display: '₹300.00',
  sample_size: 40,
  is_thin: false,
};

const shop: Provider = {
  id: 1,
  display_name: 'Sharp Cuts Studio',
  service_type: 'men',
  service_type_label: "Men's salon",
  photo: null,
  rating_average: 4.8,
  rating_count: 120,
  is_open_now: true,
  is_accepting_bookings: true,
  starting_price_display: '₹250.00',
  approximate_location: { lat: 12.9716, lng: 77.5946 },
};

function mockApi(prices: PriceBand[] = [band], results: Provider[] = [shop], next: string | null = null) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const body = url.includes('/providers/prices/')
        ? { bands: prices }
        : { count: results.length, next, previous: null, results };
      return { ok: true, status: 200, json: async () => body };
    }),
  );
}

describe('ShopCard', () => {
  it('shows the name, meta and starting price', () => {
    render(<ShopCard provider={shop} origin={null} />);

    expect(screen.getByRole('heading', { name: 'Sharp Cuts Studio' })).toBeInTheDocument();
    expect(screen.getByText(/Men's salon · Open now · 4.8 from 120/)).toBeInTheDocument();
    expect(screen.getByText('₹250.00')).toBeInTheDocument();
  });

  it('says when a shop is not taking bookings', () => {
    render(<ShopCard provider={{ ...shop, is_accepting_bookings: false }} origin={null} />);
    expect(screen.getByText('Not taking bookings')).toBeInTheDocument();
  });

  it('says so when there are no reviews', () => {
    render(<ShopCard provider={{ ...shop, rating_count: 0, rating_average: null }} origin={null} />);
    expect(screen.getByText(/No reviews yet/)).toBeInTheDocument();
  });

  it('shows a distance once there is an origin', () => {
    render(<ShopCard provider={shop} origin={{ lat: 12.98, lng: 77.6 }} />);
    expect(screen.getByText(/km away/)).toBeInTheDocument();
  });

  it('falls back to an initial when there is no photo', () => {
    const { container } = render(<ShopCard provider={shop} origin={null} />);
    expect(container.querySelector('.shop-avatar-fallback')?.textContent).toBe('S');
  });

  it('uses a real image when there is one', () => {
    render(<ShopCard provider={{ ...shop, photo: 'https://x/y.png' }} origin={null} />);
    expect(screen.getByRole('presentation', { hidden: true })).toBeInTheDocument();
  });
});

describe('PriceCard', () => {
  it('leads with the typical figure and shows the range', () => {
    render(<PriceCard band={band} />);

    expect(screen.getByText('Typically ₹250.00')).toBeInTheDocument();
    expect(screen.getByText('Lowest')).toBeInTheDocument();
    expect(screen.getByText('Highest')).toBeInTheDocument();
    expect(screen.getByText(/from 40 shops/)).toBeInTheDocument();
  });

  it('labels a thin sample honestly', () => {
    render(<PriceCard band={{ ...band, is_thin: true, sample_size: 1, minimum_display: '₹250.00' }} />);

    expect(screen.getByText('Prices start around ₹250.00')).toBeInTheDocument();
    expect(screen.getByText('Median')).toBeInTheDocument();
    expect(screen.queryByText('Typical')).not.toBeInTheDocument();
  });

  it('renders nothing for an unusable band', () => {
    const { container } = render(<PriceCard band={{ ...band, median_display: null as unknown as string }} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('ShopList', () => {
  it('explains an empty platform rather than showing a blank', () => {
    render(<ShopList shops={[]} origin={null} />);
    expect(screen.getByText(/No shops listed yet/)).toBeInTheDocument();
  });
});

describe('the page', () => {
  beforeEach(() => {
    mockApi();
    vi.stubEnv('BARBERSHOP_API_URL', '');
  });

  it('renders the hero and the live numbers', async () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { level: 1, name: /A barber you can actually book/ })).toBeInTheDocument();
    expect(await screen.findByText('Sharp Cuts Studio')).toBeInTheDocument();
    expect(await screen.findByText('Typically ₹250.00')).toBeInTheDocument();
  });

  it('shows the knowledge base link', () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );
    const inNav = within(screen.getByRole('navigation', { name: 'Main' }));
    expect(inNav.getByRole('link', { name: 'Knowledge base' })).toHaveAttribute(
      'href',
      '/knowledge',
    );
  });
});

describe('when the API is down', () => {
  it('still renders the page and says what is missing', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) })),
    );

    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );

    // A blank page is the one outcome that loses the visitor.
    expect(screen.getByRole('heading', { level: 1, name: /A barber you can actually book/ })).toBeInTheDocument();
    expect(await screen.findByText(/Prices are not loading/)).toBeInTheDocument();
    expect(screen.getByText(/Shops are not loading/)).toBeInTheDocument();
  });
});