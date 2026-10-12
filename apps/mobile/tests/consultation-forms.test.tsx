/**
 * Consultation forms, from the customer's chair.
 *
 * The server owns the rules — which questions apply, which are required, what
 * counts as a valid answer. What is worth testing here is that the app asks
 * the right questions for the services that were picked, sends the answers
 * with the booking, and refuses to let somebody confirm past a required one.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactNode } from 'react';

import { BookingSheet } from '@/components/booking-sheet';
import { BookingRow, formatWhen } from '@/components/booking-row';

const mockQuote = jest.fn();
const mockCreate = jest.fn();

const mockState: {
  priced: Record<string, unknown> | undefined;
  points: Record<string, unknown> | undefined;
  questions: Record<string, unknown>[];
} = { priced: undefined, points: undefined, questions: [] };

jest.mock('@/api/endpoints', () => {
  const actual = jest.requireActual('@/api/endpoints');
  return {
    ...actual,
    bookingsApi: {
      ...actual.bookingsApi,
      quote: (...args: unknown[]) => mockQuote(...args),
      create: (...args: unknown[]) => mockCreate(...args),
    },
  };
});

jest.mock('@/api/hooks', () => {
  const actual = jest.requireActual('@/api/hooks');
  return {
    ...actual,
    useQuote: () => ({
      data: mockState.priced,
      isPending: false,
      mutateAsync: mockQuote,
      reset: jest.fn(),
    }),
    usePointsBalance: () => ({ data: mockState.points }),
    useConsultationPrompt: () => ({
      data: mockState.questions.length
        ? { forms: [{ id: 1, name: 'Colour consultation', description: 'So we get the shade right.' }], questions: mockState.questions }
        : { forms: [], questions: [] },
    }),
    useShopStaff: () => ({ data: [] }),
  };
});

jest.mock('expo-router', () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn(), back: jest.fn() }),
}));

function aQuote() {
  return {
    currency: 'INR',
    subtotal: 20000,
    subtotal_display: '₹200',
    platform_fee: 200,
    platform_fee_display: '₹2',
    total: 20200,
    total_display: '₹202',
    deposit_percent: 50,
    deposit: 10100,
    deposit_display: '₹101',
    balance: 10100,
    balance_display: '₹101',
    cancellation_window_hours: 24,
    late_cancel_fee_percent: 0,
    late_cancel_fee: 0,
    late_cancel_fee_display: '₹0',
    duration_minutes: 30,
    starts_at: '2026-03-02T10:00:00Z',
    ends_at: '2026-03-02T10:30:00Z',
    promo_code: null,
    promo_description: '',
    points_spent: 0,
    points_worth_minor: 0,
    items: [
      {
        service_id: 1,
        name: 'Haircut',
        unit_price: 20000,
        unit_price_display: '₹200',
        duration_minutes: 30,
      },
    ],
    is_available: true,
  };
}

const SLOT = '2026-03-02T10:00:00Z';

const PROVIDER = {
  id: 1,
  display_name: 'Sharp Cuts Studio',
  slug: 'sharp-cuts',
  services: [
    {
      id: 1,
      name: 'Colour service',
      price: 20000,
      price_display: '₹200',
      duration_minutes: 30,
      is_active: true,
    },
  ],
} as never;

const AVAILABILITY = {
  date: '2026-03-02',
  slots: [{ starts_at: SLOT, is_available: true }],
} as never;

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: {
      mutations: { retry: false, gcTime: 0 },
      queries: { retry: false, gcTime: 0 },
    },
  });
  return (
    <SafeAreaProvider
      initialMetrics={{
        frame: { x: 0, y: 0, width: 390, height: 844 },
        insets: { top: 47, left: 0, right: 0, bottom: 34 },
      }}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </SafeAreaProvider>
  );
}

async function openSheet() {
  await render(
    <BookingSheet visible onClose={jest.fn()} provider={PROVIDER} availability={AVAILABILITY} />,
    { wrapper },
  );
  fireEvent.press(await screen.findByTestId('book-service-1'));
  fireEvent.press(await screen.findByText(formatWhen(SLOT)));
}

beforeEach(() => {
  mockQuote.mockReset();
  mockCreate.mockReset();
  mockCreate.mockResolvedValue({ reference: 'BK-1' });
  mockState.priced = aQuote();
  mockState.points = undefined;
  mockState.questions = [];
});

describe('asking the questions', () => {
  it('shows nothing when no service carries a form', async () => {
    await openSheet();

    expect(screen.queryByText('Before we start')).toBeNull();
  });

  it('shows the shop\'s reason for asking', async () => {
    mockState.questions = [
      { id: 1, form: 1, label: 'Have you had colour before?', kind: 'yes_no', choices: [], is_required: true },
    ];

    await openSheet();

    expect(await screen.findByText('So we get the shade right.')).toBeOnTheScreen();
  });

  it('renders a yes/no as two taps, not a keyboard', async () => {
    mockState.questions = [
      { id: 1, form: 1, label: 'Have you had colour before?', kind: 'yes_no', choices: [], is_required: true },
    ];

    await openSheet();

    expect(await screen.findByTestId('question-1-yes')).toBeOnTheScreen();
    expect(screen.queryByTestId('question-1')).toBeNull();
  });

  it('renders a pick-one as the choices given, and nothing else', async () => {
    mockState.questions = [
      {
        id: 1,
        form: 1,
        label: 'How blunt?',
        kind: 'choice',
        choices: ['Just tidy', 'Not too much'],
        is_required: true,
      },
    ];

    await openSheet();

    expect(await screen.findByTestId('question-1-choice-Just tidy')).toBeOnTheScreen();
    expect(screen.queryByTestId('question-1-choice-Shave it')).toBeNull();
  });

  it('sends the answers with the booking', async () => {
    mockState.questions = [
      { id: 1, form: 1, label: 'Have you had colour before?', kind: 'yes_no', choices: [], is_required: true },
      { id: 2, form: 1, label: 'Any medical notes?', kind: 'short_text', choices: [], is_required: false },
    ];

    await openSheet();
    fireEvent.press(await screen.findByTestId('question-1-yes'));
    fireEvent.changeText(await screen.findByTestId('question-2'), 'Ears, badly pierced');
    fireEvent.press(await screen.findByTestId('book-confirm'));

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    expect(mockCreate.mock.calls[0][0].answers).toEqual([
      { question: 1, value: 'yes' },
      { question: 2, value: 'Ears, badly pierced' },
    ]);
  });

  it('leaves a blank optional question out entirely', async () => {
    mockState.questions = [
      { id: 1, form: 1, label: 'Have you had colour before?', kind: 'yes_no', choices: [], is_required: true },
      { id: 2, form: 1, label: 'Anything else?', kind: 'short_text', choices: [], is_required: false },
    ];

    await openSheet();
    fireEvent.press(await screen.findByTestId('question-1-no'));
    fireEvent.press(await screen.findByTestId('book-confirm'));

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    expect(mockCreate.mock.calls[0][0].answers).toEqual([{ question: 1, value: 'no' }]);
  });

  it('will not confirm while a required question is blank', async () => {
    mockState.questions = [
      { id: 1, form: 1, label: 'Have you had colour before?', kind: 'yes_no', choices: [], is_required: true },
    ];

    await openSheet();

    expect(await screen.findByTestId('book-confirm')).toBeDisabled();
  });

  it('confirms once it is answered', async () => {
    mockState.questions = [
      { id: 1, form: 1, label: 'Have you had colour before?', kind: 'yes_no', choices: [], is_required: true },
    ];

    await openSheet();
    fireEvent.press(await screen.findByTestId('question-1-yes'));

    await waitFor(() => expect(screen.getByTestId('book-confirm')).not.toBeDisabled());
  });

  it('sends no answers at all when the service has no form', async () => {
    await openSheet();
    fireEvent.press(await screen.findByTestId('book-confirm'));

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    expect(mockCreate.mock.calls[0][0].answers).toEqual([]);
  });
});

describe('reading the answers', () => {
  const booking = {
    id: 1,
    reference: 'BK-1',
    provider: { id: 1, display_name: 'Sharp Cuts Studio' },
    customer: { id: 2, username: 'sam', display_name: 'Sam' },
    status: 'confirmed',
    starts_at: SLOT,
    ends_at: '2026-03-02T10:30:00Z',
    duration_minutes: 30,
    subtotal: 20000,
    platform_fee: 200,
    total: 20200,
    total_display: '₹202',
    currency: 'INR',
    deposit: 0,
    balance: 20200,
    amount_paid: 10100,
    amount_due: 10100,
    requires_deposit: true,
    notes: '',
    items: [{ name: 'Colour service', quantity: 1, unit_price: 20000, total: 20000 }],
    can_be_cancelled: true,
    consultation_answers: [
      { id: 1, question: 1, label: 'Have you had colour before?', value: 'yes', is_sensitive: false },
      { id: 2, question: 2, label: 'Any medical notes?', value: 'Ears', is_sensitive: true },
    ],
  };

  it('the provider sees the answers on the row', async () => {
    await render(
      <BookingRow booking={booking as never} perspective="provider" statusLabel="Confirmed" />,
      { wrapper },
    );

    expect(await screen.findByText('Have you had colour before?')).toBeOnTheScreen();
    expect(screen.getByText('Ears')).toBeOnTheScreen();
  });

  it('a private answer is marked as such', async () => {
    await render(
      <BookingRow booking={booking as never} perspective="provider" statusLabel="Confirmed" />,
      { wrapper },
    );

    expect(await screen.findByText('Any medical notes? · private')).toBeOnTheScreen();
  });

  it('the customer is not shown the answers at all', async () => {
    await render(
      <BookingRow
        booking={{ ...booking, consultation_answers: [] } as never}
        perspective="customer"
        statusLabel="Confirmed"
      />,
      { wrapper },
    );

    expect(screen.queryByText('Have you had colour before?')).toBeNull();
  });
});