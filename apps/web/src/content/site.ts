/**
 * Marketing copy and links for the public site.
 *
 * The site is deliberately static: it is a front door to the app and a
 * knowledge base, not a second client. Keeping every claim in one file makes
 * it easy to check that the page describes the product that actually exists.
 */

export interface StoreLink {
  id: 'ios' | 'android';
  eyebrow: string;
  store: string;
  platform: string;
  href: string;
}

/**
 * Store listings.
 *
 * The App Store link is a search until a numeric app id exists; the Play link
 * uses the package name from `apps/mobile/app.json`. Both live here so there
 * is one place to update when the listings go live.
 */
export const STORE_LINKS: StoreLink[] = [
  {
    id: 'ios',
    eyebrow: 'Download on the',
    store: 'App Store',
    platform: 'iPhone and iPad',
    href: 'https://apps.apple.com/us/search?term=BarberShop',
  },
  {
    id: 'android',
    eyebrow: 'Get it on',
    store: 'Google Play',
    platform: 'Android phones and tablets',
    href: 'https://play.google.com/store/apps/details?id=com.barbershop.app',
  },
];

/**
 * The artwork key names the illustration that belongs to a feature. Keeping it
 * here rather than matching on the title means copy can change without the
 * picture quietly becoming the wrong one.
 */
export type FeatureArt =
  | 'nearby'
  | 'availability'
  | 'price'
  | 'deposit'
  | 'reminder'
  | 'products'
  | 'hours'
  | 'ledger'
  | 'refund'
  | 'earnings'
  | 'team'
  | 'orders';

export interface Feature {
  title: string;
  body: string;
  art: FeatureArt;
}

export const CUSTOMER_FEATURES: Feature[] = [
  {
    title: 'Shops near you, ranked',
    body: 'See who is nearby, what they charge and whether they are open right now.',
    art: 'nearby',
  },
  {
    title: 'Availability that is real',
    body: 'Slots come from the shop’s own calendar, so a time that shows is a time you can take.',
    art: 'availability',
  },
  {
    title: 'The price before you confirm',
    body: 'The full amount — including any deposit and the platform fee — is shown before you book.',
    art: 'price',
  },
  {
    title: 'Deposits and the balance',
    body: 'Pay part up front if the shop asks for it, then settle the rest at the chair.',
    art: 'deposit',
  },
  {
    title: 'Reminders and a waitlist',
    body: 'Get a nudge before the appointment, or join the waitlist when the time you want is gone.',
    art: 'reminder',
  },
  {
    title: 'Products from your shop',
    body: 'Order the products your barber uses, delivered or ready to collect.',
    art: 'products',
  },
];

export const PROVIDER_FEATURES: Feature[] = [
  {
    title: 'Your calendar, your hours',
    body: 'Set the week you work and only those slots are ever offered. Pause bookings whenever you need.',
    art: 'hours',
  },
  {
    title: 'Deposits and balances',
    body: 'Take a deposit, record the balance at the chair, and let the booking show what is still owed.',
    art: 'ledger',
  },
  {
    title: 'No-shows and refunds',
    body: 'Mark a no-show, issue a full or partial refund, and keep the record attached to the booking.',
    art: 'refund',
  },
  {
    title: 'Earnings and payouts',
    body: 'See what is pending, what is available, and withdraw to your verified bank account.',
    art: 'earnings',
  },
  {
    title: 'Staff, services and stock',
    body: 'Run the shop’s team, menu and product shelf from the same app your customers use.',
    art: 'team',
  },
  {
    title: 'Product orders',
    body: 'Receive orders with the fulfilment the customer chose and mark them ready or delivered.',
    art: 'orders',
  },
];

export type StepArt = 'download' | 'find' | 'book';

export interface Step {
  title: string;
  body: string;
  art: StepArt;
}

export const BOOKING_STEPS: Step[] = [
  {
    title: 'Download the app',
    body: 'One app for customers and providers. Pick your role when you sign up and the app reshapes around it.',
    art: 'download',
  },
  {
    title: 'Find a shop',
    body: 'Browse by distance, filter to the shops open now, and check the price range before you choose.',
    art: 'find',
  },
  {
    title: 'Pick a slot and book',
    body: 'Take a time from the shop’s real calendar, see the full price, and get a reminder before the day.',
    art: 'book',
  },
];

export interface PopularQuestion {
  question: string;
  /** Entry id in `src/content/knowledge.ts`; the link lands on that answer. */
  entryId: string;
  tag: string;
}

export const POPULAR_QUESTIONS: PopularQuestion[] = [
  { question: 'Why is there a deposit?', entryId: 'deposits', tag: 'Payments' },
  { question: 'How do refunds work?', entryId: 'refund-how', tag: 'Refunds' },
  { question: 'What if the shop cancels on me?', entryId: 'provider-cancels', tag: 'Cancellations' },
  { question: 'How do I withdraw my earnings?', entryId: 'withdraw', tag: 'Payouts' },
];
