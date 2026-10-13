/**
 * Managing API keys.
 *
 * One behaviour carries the whole feature: the secret is shown once, and the
 * screen has to say so at the moment it is shown. Everything after that is
 * bookkeeping - but a user who does not know the secret is gone for good will
 * not copy it, and the integration they were setting up silently fails.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactNode } from 'react';

import ApiKeysScreen from '../app/(customer)/api-keys';

const mockCreate = jest.fn();
const mockRevoke = jest.fn();

const mockState: { keys: Record<string, unknown>[] } = { keys: [] };

jest.mock('@/api/hooks', () => {
  const actual = jest.requireActual('@/api/hooks');
  return {
    ...actual,
    useApiKeys: () => ({ data: mockState.keys, isLoading: false }),
    useCreateApiKey: () => ({ mutateAsync: mockCreate, isPending: false }),
    useRevokeApiKey: () => ({ mutateAsync: mockRevoke, isPending: false }),
  };
});

function aKey(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    name: 'Front till',
    prefix: 'acde2345',
    scopes: ['read', 'write'],
    is_active: true,
    last_used_at: '2026-03-01T10:00:00Z',
    expires_at: null,
    is_expired: false,
    created_at: '2026-02-01T10:00:00Z',
    ...overrides,
  };
}

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

beforeEach(() => {
  mockCreate.mockReset();
  mockRevoke.mockReset();
  mockState.keys = [];
});

describe('creating a key', () => {
  it('starts with read only', async () => {
    mockCreate.mockResolvedValue({ ...aKey(), key: 'acde2345.secret' });
    await render(<ApiKeysScreen />, { wrapper });

    fireEvent.press(await screen.findByTestId('new-key'));
    fireEvent.changeText(await screen.findByTestId('key-name'), 'Front till');
    fireEvent.press(await screen.findByTestId('create-key'));

    await waitFor(() => expect(mockCreate).toHaveBeenCalled());
    // A key that can write by default is a key nobody deliberately made.
    expect(mockCreate.mock.calls[0][0]).toEqual({ name: 'Front till', scopes: ['read'] });
  });

  it('will not make a key that can do nothing', async () => {
    await render(<ApiKeysScreen />, { wrapper });

    fireEvent.press(await screen.findByTestId('new-key'));
    fireEvent.changeText(await screen.findByTestId('key-name'), 'Useless');
    fireEvent.press(await screen.findByTestId('scope-read'));
    fireEvent.press(await screen.findByTestId('create-key'));

    await waitFor(() => expect(screen.getByText(/can do nothing/)).toBeOnTheScreen());
    expect(mockCreate).not.toHaveBeenCalled();
  });

  it('will not make one with no name', async () => {
    await render(<ApiKeysScreen />, { wrapper });

    fireEvent.press(await screen.findByTestId('new-key'));
    fireEvent.press(await screen.findByTestId('create-key'));

    await waitFor(() => expect(screen.getByText(/recognise in six months/)).toBeOnTheScreen());
    expect(mockCreate).not.toHaveBeenCalled();
  });

  it('adds write when asked for it', async () => {
    mockCreate.mockResolvedValue({ ...aKey(), key: 'k' });
    await render(<ApiKeysScreen />, { wrapper });

    fireEvent.press(await screen.findByTestId('new-key'));
    fireEvent.changeText(await screen.findByTestId('key-name'), 'Front till');
    fireEvent.press(await screen.findByTestId('scope-write'));
    fireEvent.press(await screen.findByTestId('create-key'));

    await waitFor(() => expect(mockCreate).toHaveBeenCalled());
    expect(mockCreate.mock.calls[0][0].scopes).toEqual(['read', 'write']);
  });
});

describe('the secret', () => {
  it('is shown after creation', async () => {
    mockCreate.mockResolvedValue({ ...aKey(), key: 'acde2345.thesecret' });
    await render(<ApiKeysScreen />, { wrapper });

    fireEvent.press(await screen.findByTestId('new-key'));
    fireEvent.changeText(await screen.findByTestId('key-name'), 'Front till');
    fireEvent.press(await screen.findByTestId('create-key'));

    expect(await screen.findByTestId('issued-key')).toBeOnTheScreen();
    expect(screen.getByText('acde2345.thesecret')).toBeOnTheScreen();
  });

  it('says it is the only time', async () => {
    mockCreate.mockResolvedValue({ ...aKey(), key: 'acde2345.thesecret' });
    await render(<ApiKeysScreen />, { wrapper });

    fireEvent.press(await screen.findByTestId('new-key'));
    fireEvent.changeText(await screen.findByTestId('key-name'), 'Front till');
    fireEvent.press(await screen.findByTestId('create-key'));

    // A user who does not know this will not copy it, and the integration
    // silently fails later.
    expect(await screen.findByText(/only show it this once/)).toBeOnTheScreen();
  });

  it('can be dismissed once copied', async () => {
    mockCreate.mockResolvedValue({ ...aKey(), key: 'acde2345.thesecret' });
    await render(<ApiKeysScreen />, { wrapper });

    fireEvent.press(await screen.findByTestId('new-key'));
    fireEvent.changeText(await screen.findByTestId('key-name'), 'Front till');
    fireEvent.press(await screen.findByTestId('create-key'));
    fireEvent.press(await screen.findByTestId('dismiss-key'));

    await waitFor(() => expect(screen.queryByTestId('issued-key')).toBeNull());
  });

  it('is never shown again for an existing key', async () => {
    mockState.keys = [aKey()];

    await render(<ApiKeysScreen />, { wrapper });

    expect(await screen.findByText(/acde2345…/)).toBeOnTheScreen();
    expect(screen.queryByTestId('issued-key')).toBeNull();
  });
});

describe('revoking', () => {
  it('is offered for a live key', async () => {
    mockState.keys = [aKey()];
    mockRevoke.mockResolvedValue({ ...aKey(), is_active: false });

    await render(<ApiKeysScreen />, { wrapper });

    fireEvent.press(await screen.findByTestId('revoke-1'));

    await waitFor(() => expect(mockRevoke).toHaveBeenCalledWith(1));
  });

  it('is not offered for one already revoked', async () => {
    mockState.keys = [aKey({ is_active: false })];

    await render(<ApiKeysScreen />, { wrapper });

    expect(await screen.findByText('revoked')).toBeOnTheScreen();
    expect(screen.queryByTestId('revoke-1')).toBeNull();
  });

  it('says revoking stops it immediately', async () => {
    mockState.keys = [aKey()];

    await render(<ApiKeysScreen />, { wrapper });

    expect(await screen.findByText(/immediately/)).toBeOnTheScreen();
  });

  it('says when a key was last used', async () => {
    mockState.keys = [aKey({ last_used_at: null })];

    await render(<ApiKeysScreen />, { wrapper });

    expect(await screen.findByText('Never used')).toBeOnTheScreen();
  });
});
