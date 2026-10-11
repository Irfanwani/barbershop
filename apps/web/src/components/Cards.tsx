import type { PriceBand, Provider } from '@/lib/types';
import { describeBand, distanceLabel } from '@/lib/format';

/**
 * The shop card.
 *
 * A closed shop still shows its price, greyed rather than hidden: "why is this
 * one cheaper" is a fair question and hiding it invites a refresh that will not
 * change the answer.
 */
export function ShopCard({
  provider,
  origin,
}: {
  provider: Provider;
  origin: { lat: number; lng: number } | null;
}) {
  const initial = (provider.display_name || '?').trim().charAt(0).toUpperCase();
  const away = distanceLabel(origin, provider.approximate_location);

  const meta = [
    provider.service_type_label,
    provider.is_open_now ? 'Open now' : 'Closed now',
    provider.rating_count
      ? `${provider.rating_average} from ${provider.rating_count}`
      : 'No reviews yet',
    away,
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <article className="shop-card">
      {provider.photo ? (
        <img className="shop-avatar" src={provider.photo} alt="" loading="lazy" />
      ) : (
        <div className="shop-avatar shop-avatar-fallback" aria-hidden="true">
          {initial}
        </div>
      )}
      <div>
        <h3 className="shop-name">{provider.display_name}</h3>
        <p className="shop-meta">{meta}</p>
      </div>
      {provider.is_accepting_bookings ? (
        <p className="shop-from">
          <span>From</span>
          <strong>{provider.starting_price_display ?? '—'}</strong>
        </p>
      ) : (
        <p className="shop-from">
          <span className="shop-closed">Not taking bookings</span>
        </p>
      )}
    </article>
  );
}

/**
 * A price band card.
 *
 * The label follows the sample size. A card reading "Typical ₹300" over a note
 * saying "based on 1 shop" is a confident lie with a footnote.
 */
export function PriceCard({ band }: { band: PriceBand }) {
  const copy = describeBand(band);
  if (!copy) return null;

  return (
    <article className="price-card">
      <h3>{band.service_type_label}</h3>
      <p className="price-headline">{copy.headline}</p>
      <div className="price-figures">
        <p className="price-figure">
          <span>{copy.thin ? 'Median' : 'Typical'}</span>
          <strong>{band.median_display ?? '—'}</strong>
        </p>
        <p className="price-figure">
          <span>Lowest</span>
          <strong>{band.minimum_display ?? '—'}</strong>
        </p>
        <p className="price-figure">
          <span>Highest</span>
          <strong>{band.maximum_display ?? '—'}</strong>
        </p>
      </div>
      <p className={copy.thin ? 'price-note is-thin' : 'price-note'}>{copy.note}</p>
    </article>
  );
}

export function ShopList({
  shops,
  origin,
}: {
  shops: Provider[];
  origin: { lat: number; lng: number } | null;
}) {
  if (shops.length === 0) {
    return <p className="muted">No shops listed yet. Once providers sign up they appear here.</p>;
  }
  return (
    <>
      {shops.map((provider) => (
        <ShopCard key={provider.id} provider={provider} origin={origin} />
      ))}
    </>
  );
}