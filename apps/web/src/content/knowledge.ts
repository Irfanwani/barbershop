/**
 * The knowledge base.
 *
 * Written as data rather than as components so it can be checked: a test
 * asserts every section has an id (anchors are linkable), that the search index
 * covers every entry, and that nothing promises a feature that does not exist.
 *
 * Content here describes only what the product does today. Where something is
 * planned rather than shipped, it is marked as such rather than described in
 * the present tense — a knowledge base that documents the roadmap as though it
 * were the product is worse than none.
 */

export interface Entry {
  id: string;
  question: string;
  answer: string;
  /** Words a visitor might plausibly type that are not in the question. */
  keywords?: string[];
}

export interface Section {
  id: string;
  title: string;
  blurb: string;
  entries: Entry[];
}

export interface Group {
  id: string;
  title: string;
  summary: string;
  audience: 'customers' | 'providers' | 'both';
  sections: Section[];
}

export const GROUPS: Group[] = [
  {
    id: 'booking',
    title: 'Booking an appointment',
    summary:
      'Finding a shop, choosing a time, and what you pay — including deposits, so you know the number before you commit.',
    audience: 'customers',
    sections: [
      {
        id: 'finding-a-shop',
        title: 'Finding a shop',
        blurb: 'Search, sorting, and what the numbers on a shop card mean.',
        entries: [
          {
            id: 'how-to-find-a-shop',
            question: 'How do I find a shop near me?',
            answer:
              'Open the app or the website and allow location sharing, and the list is sorted by how far away each shop is. Your coordinates are used in your browser to sort the list and are not stored on our servers. Without location, you get every shop instead, unsorted.',
            keywords: ['near me', 'location', 'search', 'sort', 'distance', 'nearby'],
          },
          {
            id: 'open-now',
            question: 'What does "Open now" mean?',
            answer:
              'It is the shop\'s own weekly hours checked against the current time in the shop\'s local timezone. A shop that is closed still shows its prices and reviews, greyed rather than hidden — "why is this one cheaper" is a fair question, and hiding the answer just invites a refresh that will not change it.',
            keywords: ['open', 'closed', 'hours', 'timing', 'now'],
          },
          {
            id: 'not-taking-bookings',
            question: 'Why does a shop say "Not taking bookings"?',
            answer:
              'The provider has paused bookings, usually for a holiday or a busy period. The shop stays listed and you can still see prices and reviews. Nothing is wrong with it and nothing needs fixing.',
            keywords: ['closed for bookings', 'paused', 'unavailable', 'not accepting'],
          },
          {
            id: 'real-availability',
            question: 'How real is the availability?',
            answer:
              'It is the provider\'s own calendar, not a guess. Slots appear only where the provider has set working hours and nothing else is booked, and they disappear the moment someone else takes them. If a shop is shut on Sunday, Sunday is never offered.',
            keywords: ['availability', 'calendar', 'slots', 'free', 'genuine'],
          },
          {
            id: 'rating-a-shop',
            question: 'What does the rating mean?',
            answer:
              'The average of reviews left by people who actually had the appointment, not people who only browsed. The count is shown next to it so you can tell a 5.0 from one review apart from a 5.0 from five hundred.',
            keywords: ['reviews', 'rating', 'stars', 'feedback', 'trust'],
          },
        ],
      },
      {
        id: 'paying',
        title: 'Paying: prices, deposits and the balance',
        blurb:
          'The number you are shown is the number you pay. Deposits, the remaining balance, and how each is collected.',
        entries: [
          {
            id: 'price-before-you-pay',
            question: 'Where does the price come from?',
            answer:
              'The provider lists their own prices, and you see the full total — including the platform fee — before you confirm. The price is fixed on your booking the moment you make it and cannot change afterwards, even if the provider edits their price list later.',
            keywords: ['cost', 'fee', 'how much', 'quote', 'price', '1%', 'charged'],
          },
          {
            id: 'deposits',
            question: 'Why is there a deposit?',
            answer:
              'Some shops ask for part of the price up front to hold the slot, and the rest on the day. A booking with a deposit is confirmed as soon as it is paid; without one it is held provisionally until you pay. The split is set by the shop and shown to you before you confirm — you never find out the amount after booking.',
            keywords: ['deposit', 'advance', 'partial', 'upfront', 'hold', 'slot'],
          },
          {
            id: 'paying-the-balance',
            question: 'How do I pay the remaining amount?',
            answer:
              'At the shop when you arrive: cash, UPI or card. Your booking shows what is still owed so the provider can tell you, and it updates as soon as it is paid. A booking paid by deposit is never asked for the full amount again at the counter.',
            keywords: ['balance', 'remaining', 'pay at shop', 'cash', 'upi', 'card', 'counter'],
          },
          {
            id: 'no-surprise-charges',
            question: 'What happens if the price changes after I book?',
            answer:
              'It does not. The price is frozen on your booking when you make it. Neither the provider nor the platform can raise it afterwards.',
            keywords: ['price change', 'surprise', 'extra charge', 'frozen', 'locked'],
          },
        ],
      },
    ],
  },
  {
    id: 'changes',
    title: 'Cancelling, refunds and no-shows',
    summary:
      'What you can cancel, when, what it costs, and how a refund gets back to you.',
    audience: 'customers',
    sections: [
      {
        id: 'cancellation',
        title: 'Cancelling a booking',
        blurb: 'The window, the fee, and who it never applies to.',
        entries: [
          {
            id: 'cancel-window',
            question: 'Can I cancel?',
            answer:
              'Yes, from your bookings screen. How much notice matters: each shop sets a cancellation window, and cancelling inside it can carry a fee. The shop\'s policy is shown to you in full before you confirm a booking, so you always know the terms before committing rather than after.',
            keywords: ['cancel', 'cancellation', 'change of plan', 'refund policy', 'window', 'notice'],
          },
          {
            id: 'cancellation-fee',
            question: 'Why is there a cancellation charge?',
            answer:
              'Because the slot was held for you and cannot necessarily be resold, especially close to the appointment. The amount is a percentage the shop sets and it is frozen onto your booking, so it cannot be raised after you book. Cancel early and there is normally no charge at all.',
            keywords: ['cancellation charge', 'penalty', 'fee', 'why charged', 'late cancel'],
          },
          {
            id: 'no-show-fee',
            question: 'What if I do not turn up?',
            answer:
              'A missed appointment inside the cancellation window carries the same fee as a late cancellation. It exists because the provider kept the slot and cannot sell it twice.',
            keywords: ['no show', 'did not turn up', 'missed', 'absent', 'didnt come'],
          },
          {
            id: 'provider-cancels',
            question: 'What if the shop cancels on me?',
            answer:
              'You are never charged a cancellation fee for a cancellation made by the provider — the penalty only ever applies when you cancel. Any deposit you paid is refunded.',
            keywords: ['shop cancels', 'provider cancels', 'they cancelled', 'their fault'],
          },
        ],
      },
      {
        id: 'refunds',
        title: 'Refunds',
        blurb: 'How long it takes, where it goes, and how to check on it.',
        entries: [
          {
            id: 'refund-how',
            question: 'How do refunds work?',
            answer:
              'Refunds go back to the original payment method — the same card or UPI you paid with. The provider processes it from their account; you do not need to ask us. A refund that is due to you is always refunded, including a deposit.',
            keywords: ['refund', 'money back', 'return', 'reimbursement', 'get my money'],
          },
          {
            id: 'refund-timing',
            question: 'How long does a refund take?',
            answer:
              'It is raised immediately, but the time to appear depends on your bank, usually a few working days. Card refunds are typically slower than UPI. Check with your provider for the exact status of your refund.',
            keywords: ['how long', 'when', 'days', 'waiting', 'still not received', 'slow'],
          },
          {
            id: 'refund-status',
            question: 'How do I check a refund has gone through?',
            answer:
              'Your booking shows the amount paid and the amount still owed, and the refund appears on the booking as it is processed. If the figures do not match what you were told, contact the provider who took the booking.',
            keywords: ['check', 'status', 'processed', 'see refund', 'confirm refund'],
          },
        ],
      },
    ],
  },
  {
    id: 'shop',
    title: 'Products and shop services',
    summary: 'Buying the products a shop uses, and having them delivered or collected.',
    audience: 'customers',
    sections: [
      {
        id: 'products',
        title: 'Buying products',
        blurb: 'The product shelf, stock, and orders.',
        entries: [
          {
            id: 'buy-products',
            question: 'Can I buy the products a shop uses?',
            answer:
              'Yes. Shops list the products they stock in the app and you can order them directly. Prices and stock are shown per shop, so you see what that particular shop charges rather than a generic price.',
            keywords: ['products', 'shampoo', 'buy', 'shop', 'order', 'retail', 'store'],
          },
          {
            id: 'stock',
            question: 'What does "out of stock" mean?',
            answer:
              'The shop does not have it right now. Stock is tracked per shop and per product and is checked again when you order, so an item that was available when you looked may have sold out in the meantime.',
            keywords: ['stock', 'unavailable', 'sold out', 'available', 'inventory'],
          },
          {
            id: 'fulfilment',
            question: 'Can I have a product delivered or collected?',
            answer:
              'Either. When you order you choose how you want it — delivered to your address, or ready to collect from the shop. Delivery addresses are only used to fulfil your order.',
            keywords: ['delivery', 'deliver', 'collect', 'pickup', 'shipping', 'home'],
          },
        ],
      },
    ],
  },
  {
    id: 'provider',
    title: 'Running a shop on BarberShop',
    summary:
      'For providers: setting up, taking bookings, being paid, and the shop\'s product shelf.',
    audience: 'providers',
    sections: [
      {
        id: 'getting-started',
        title: 'Setting up and working hours',
        blurb: 'Your profile, when you are open, and pausing when you are not.',
        entries: [
          {
            id: 'set-hours',
            question: 'How do I set my working hours?',
            answer:
              'From your profile, set the hours you work each day of the week. Only slots inside those hours are ever offered, and they are stored with your profile so they survive a device change. Holidays and irregular time off go on your calendar, not in your weekly hours.',
            keywords: ['hours', 'schedule', 'availability', 'working', 'timetable', 'open'],
          },
          {
            id: 'pause-bookings',
            question: 'How do I stop taking bookings temporarily?',
            answer:
              'Turn off "accepting bookings" on your profile. You stay listed with your prices and reviews, but no new bookings can be made. Customers already booked are unaffected. Turn it back on when you are ready.',
            keywords: ['pause', 'stop bookings', 'holiday', 'break', 'away', 'offline'],
          },
        ],
      },
      {
        id: 'taking-bookings',
        title: 'Taking and running bookings',
        blurb: 'Deposits you collect, the balance at the chair, and what the app shows you.',
        entries: [
          {
            id: 'collect-deposit',
            question: 'How do I take a deposit at my shop?',
            answer:
              'Open the booking in your provider app and mark the deposit as collected. The customer\'s balance updates immediately and they can see they have paid. You can take cash, UPI or card, and you record how it was paid so your own books add up.',
            keywords: ['deposit', 'collect', 'payment', 'mark paid', 'cash', 'counter'],
          },
          {
            id: 'collect-balance',
            question: 'How do I collect the balance on the day?',
            answer:
              'Mark the balance as collected from the booking. The booking then shows as fully paid. A customer who paid a deposit is only ever asked for the remainder, not the full price again.',
            keywords: ['balance', 'remaining', 'collect', 'full payment', 'complete payment'],
          },
          {
            id: 'no-shows',
            question: 'How do I handle a no-show?',
            answer:
              'Mark the booking as a no-show from the booking screen. A no-show inside your cancellation window is charged your cancellation fee, and that is the only way a fee is ever applied. A customer who cancels, or who you cancel, is never charged.',
            keywords: ['no show', 'did not arrive', 'mark no show', 'absent', 'charge fee'],
          },
          {
            id: 'refund-a-customer',
            question: 'How do I refund a customer?',
            answer:
              'From the booking, issue a refund for all or part of what they paid. It goes back to their original payment method and updates their booking straight away. You can refund a full payment or just the deposit.',
            keywords: ['refund', 'return money', 'give back', 'partial refund', 'issue refund'],
          },
          {
            id: 'reschedule',
            question: 'Can I move an appointment to another time?',
            answer:
              'Yes — "Change the time" on the booking screen. It is the same booking, so the reference, your payments and your reminders all follow it. The price is checked again when you move it: if the service now costs a different amount you will see both figures and be asked to agree, rather than being quietly charged either the old or the new one. Close to the appointment it becomes a cancellation instead, on the same terms as cancelling would have been.',
            keywords: ['reschedule', 'move appointment', 'change time', 'postpone', 'different day'],
          },
        ],
      },
      {
        id: 'getting-paid',
        title: 'Getting paid',
        blurb: 'Your earnings, your statement, and taking money out.',
        entries: [
          {
            id: 'earnings-balance',
            question: 'Where do I see what I have earned?',
            answer:
              'The Earnings tab in your provider app. It shows what is available to withdraw, what is still pending, and a statement you can read line by line.',
            keywords: ['earnings', 'balance', 'money', 'income', 'statement', 'earned'],
          },
          {
            id: 'pending-vs-available',
            question: 'Why is some money pending?',
            answer:
              'Pending money is from appointments that have not happened yet. It becomes available when the appointment is finished, because until then it can still be cancelled or missed. Only completed appointments can be withdrawn, and they can be withdrawn in full without a delay.',
            keywords: ['pending', 'available', 'clearance', 'why pending', 'hold', 'payout delay'],
          },
          {
            id: 'platform-fee',
            question: 'Why is 1% taken from my earnings?',
            answer:
              'BarberShop charges providers 1% of a completed booking. It is taken as its own line on your statement rather than quietly reducing what you are paid, so you can see exactly what it was for. Customers are told about it before they book.',
            keywords: ['1%', 'commission', 'fee', 'take', 'cut', 'percentage', 'why deducted'],
          },
          {
            id: 'withdraw',
            question: 'How do I withdraw my earnings?',
            answer:
              'From the Earnings tab, withdraw everything available. The money goes to your registered bank account, which you set up in Payout account. You can only withdraw to a verified account, and you cannot withdraw money that has not cleared.',
            keywords: ['withdraw', 'payout', 'get paid', 'transfer', 'bank', 'cash out', 'money out'],
          },
          {
            id: 'bank-account',
            question: 'Why can I not change my bank account number?',
            answer:
              'Account numbers are write-only: we show them masked and cannot show you the full number back. Changing them means entering the number and IFSC again, deliberately — a field that cannot be read back cannot leak through a screenshot or a support ticket.',
            keywords: ['bank details', 'account number', 'ifsc', 'change payout', 'masked'],
          },
          {
            id: 'withdrawal-failed',
            question: 'A withdrawal failed. Where is my money?',
            answer:
              'It is back in your available balance, and the failed line is still on your statement marked as failed so you can see what happened. Nothing is lost and no duplicate withdrawal is possible — the failed request cannot be charged against you again.',
            keywords: ['failed', 'failed payout', 'money back', 'transfer failed', 'declined'],
          },
        ],
      },
      {
        id: 'shop-products',
        title: 'Selling products',
        blurb: 'Your shelf, your stock, and your orders.',
        entries: [
          {
            id: 'list-products',
            question: 'How do I sell products?',
            answer:
              'Add the products you stock with their price and how much you have. Stock is tracked per product so a customer cannot buy what you have already sold.',
            keywords: ['list products', 'add products', 'stock', 'inventory', 'sell', 'shelf'],
          },
          {
            id: 'fulfil-orders',
            question: 'How do I fulfil an order?',
            answer:
              'Product orders land in your provider app with the fulfilment the customer chose — delivery or collect. Mark it delivered or ready, and the customer is notified.',
            keywords: ['fulfil', 'order', 'deliver', 'ready', 'collect', 'ship'],
          },
        ],
      },
    ],
  },
  {
    id: 'account',
    title: 'Your account and your data',
    summary: 'Signing in, notifications, and what we do and do not keep.',
    audience: 'both',
    sections: [
      {
        id: 'account-basics',
        title: 'Account basics',
        blurb: 'Sign-in, reminders, and reviews.',
        entries: [
          {
            id: 'sign-in',
            question: 'How do I sign in?',
            answer:
              'With the phone number you registered and a one-time code. You can sign in on more than one device; your bookings, balances and settings are all tied to your account rather than to a phone.',
            keywords: ['sign in', 'login', 'log in', 'otp', 'code', 'password', 'account'],
          },
          {
            id: 'waitlist',
            question: 'The time I want is taken. Can I wait for a cancellation?',
            answer:
              'Yes. On a shop\u2019s page, if nothing is free in the next week you can join the waitlist for that service. When a booked slot is cancelled it is offered to whoever joined first, and held for them for a short window before it goes back to being public. You get a countdown saying how long it is yours, so it is never a silent race.',
            keywords: ['waitlist', 'cancellation', 'cancelled', 'waiting list', 'free slot', 'wait'],
          },
          {
            id: 'save-a-shop',
            question: 'Can I save a shop?',
            answer:
              'Yes — Save on any shop, and they come first when you browse. A saved shop stays saved even if the shop pauses for a holiday, so it reappears at the top of your list when it reopens rather than disappearing and having to be found again.',
            keywords: ['save', 'saved', 'favourite', 'favorite', 'bookmark', 'usual place'],
          },
          {
            id: 'reminders',
            question: 'Will I be reminded about an appointment?',
            answer:
              'Yes, before each appointment, so nobody is left waiting. Reminders are sent for bookings you have not cancelled, and a booking that is cancelled does not remind you.',
            keywords: ['reminder', 'notification', 'alert', 'remind me', 'sms', 'push'],
          },
          {
            id: 'leave-a-review',
            question: 'When can I leave a review?',
            answer:
              'After an appointment has actually happened, from the booking itself. That is deliberate: it keeps ratings a measure of service received rather than of who reviewed most.',
            keywords: ['review', 'rate', 'rating', 'feedback', 'stars', 'leave review'],
          },
        ],
      },
      {
        id: 'privacy',
        title: 'Privacy',
        blurb: 'What is stored, what is not, and who sees it.',
        entries: [
          {
            id: 'location-not-stored',
            question: 'Do you store my location?',
            answer:
              'Not for browsing. Your coordinates are used in your browser to sort shops by distance and are not written to our servers. A booking does involve the provider knowing where the appointment is, because they have to be there.',
            keywords: ['location', 'privacy', 'gps', 'tracking', 'stored'],
          },
          {
            id: 'who-sees-booking',
            question: 'Who can see my booking?',
            answer:
              'The provider you booked with, and nobody else. A shop\'s other customers never see your name, your address, or that you were there.',
            keywords: ['privacy', 'who can see', 'other customers', 'my data', 'visibility'],
          },
          {
            id: 'delete-account',
            question: 'Can I delete my account?',
            answer:
              'Yes, from your account settings. Deleting removes your personal details. Past bookings may be kept in anonymised form because a provider needs a record of what was paid for.',
            keywords: ['delete', 'remove account', 'close account', 'erase', 'gdpr'],
          },
        ],
      },
    ],
  },
];

/**
 * Capabilities that are known to be shipped.
 *
 * Exists so a test can check the knowledge base does not describe any of them
 * as unavailable. The existing test only ran the other way — that anything
 * described as unshipped says so — which is why a shipped feature sat here
 * claiming it was "on the roadmap" for several releases after it existed.
 *
 * **Add to this in the same commit that ships the feature.**
 */
export const SHIPPED_CAPABILITIES: { capability: string; mustMention: string }[] = [
  { capability: 'Rescheduling', mustMention: 'Change the time' },
  { capability: 'Staff', mustMention: 'barber' },
  { capability: 'Waitlist', mustMention: 'waitlist' },
  { capability: 'Saved shops', mustMention: 'Save' },
  { capability: 'Deposits', mustMention: 'deposit' },
  { capability: 'Refunds', mustMention: 'refund' },
  { capability: 'Payouts', mustMention: 'withdraw' },
];

/** Every entry, flattened, for search. */
export function allEntries(): { group: Group; section: Section; entry: Entry }[] {
  return GROUPS.flatMap((group) =>
    group.sections.flatMap((section) =>
      section.entries.map((entry) => ({ group, section, entry })),
    ),
  );
}

/**
 * Rank entries against a query.
 *
 * Deliberately a plain substring scan. There are a few dozen entries; an index
 * is machinery that has to be kept in step with the content and would make the
 * knowledge base harder to edit, which is the only thing anyone ever does to it.
 *
 * Title matches outrank body matches, because someone searching "refund" wants
 * the refunds section before they want a passing mention.
 */
export function searchEntries(query: string): { group: Group; section: Section; entry: Entry }[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [];

  const scored: { item: ReturnType<typeof allEntries>[number]; score: number; order: number }[] = [];

  allEntries().forEach((item, order) => {
    const { question, answer, keywords } = item.entry;
    let score = 0;
    if (question.toLowerCase().includes(needle)) score += 10;
    if (keywords?.some((word) => word.toLowerCase().includes(needle))) score += 6;
    if (answer.toLowerCase().includes(needle)) score += 2;
    if (score > 0) scored.push({ item, score, order });
  });

  // Ties keep the order they appear in the knowledge base, because the first
  // entry in a section is the primary one. Alphabetical tie-breaking is
  // neither meaningful to a reader nor stable when copy is edited.
  return scored
    .sort((a, b) => b.score - a.score || a.order - b.order)
    .map((entry) => entry.item);
}

/** The audience filter used by the page. */
export function groupsFor(audience: 'all' | 'customers' | 'providers'): Group[] {
  if (audience === 'all') return GROUPS;
  return GROUPS.filter((group) => group.audience === audience || group.audience === 'both');
}