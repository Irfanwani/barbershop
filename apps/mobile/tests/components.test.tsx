/**
 * Components and stores.
 *
 * Rendering tests, aimed at the places where a quiet mistake is expensive: a
 * form field that hides an error, a settings row that looks tappable and is
 * not, and the auth store's session handling.
 */

import { fireEvent, render, screen } from '@testing-library/react-native';

import { ApiError } from '@/api/client';

import { Field, FormError } from '@/components/field';
import { SettingsList } from '@/components/settings-list';
import { Stat } from '@/components/stat';
import { Badge, Button, EmptyState } from '@/components/ui';
import { clearToken, readToken, writeToken } from '@/lib/secure-store';
import { currentToken, useAuthStore } from '@/store/auth';
import { queryClient } from '@/lib/query-client';

// ---------------------------------------------------------------------------

describe('Field', () => {
  it('labels the input so a screen reader announces it', async () => {
    await render(<Field label="Email" />);

    expect(await screen.findByLabelText('Email')).toBeOnTheScreen();
  });

  it('falls back to the placeholder when there is no label', async () => {
    await render(<Field placeholder="Search shops" />);

    expect(await screen.findByLabelText('Search shops')).toBeOnTheScreen();
  });

  it('shows the error instead of the hint when both are given', async () => {
    await render(<Field label="Email" hint="We never share it" error="That is not an email." />);

    expect(await screen.findByText('That is not an email.')).toBeOnTheScreen();
    // Showing both reads as a contradiction.
    expect(screen.queryByText('We never share it')).not.toBeOnTheScreen();
  });

  it('shows the hint when there is no error', async () => {
    await render(<Field label="Email" hint="We never share it" />);

    expect(await screen.findByText('We never share it')).toBeOnTheScreen();
  });

  it('masks a password until it is asked for, then reveals it', async () => {
    await render(<Field label="Password" secureTextEntry />);

    expect((await screen.findByLabelText('Password')).props.secureTextEntry).toBe(true);

    await fireEvent.press(await screen.findByLabelText('Show password'));
    expect((await screen.findByLabelText('Password')).props.secureTextEntry).toBe(false);

    await fireEvent.press(await screen.findByLabelText('Hide password'));
    expect((await screen.findByLabelText('Password')).props.secureTextEntry).toBe(true);
  });

  it('does not offer a reveal toggle on a plain text field', async () => {
    await render(<Field label="Username" />);

    expect(screen.queryByLabelText('Show password')).not.toBeOnTheScreen();
  });

  it('calls through onFocus and onBlur', async () => {
    const onFocus = jest.fn();
    const onBlur = jest.fn();
    await render(<Field label="Email" onFocus={onFocus} onBlur={onBlur} />);

    const input = await screen.findByLabelText('Email');
    await fireEvent(input, 'focus');
    await fireEvent(input, 'blur');

    expect(onFocus).toHaveBeenCalled();
    expect(onBlur).toHaveBeenCalled();
  });

  it('passes typed text through', async () => {
    const onChangeText = jest.fn();
    await render(<Field label="Email" onChangeText={onChangeText} />);

    await fireEvent.changeText(await screen.findByLabelText('Email'), 'jane@example.com');

    expect(onChangeText).toHaveBeenCalledWith('jane@example.com');
  });
});

describe('FormError', () => {
  it('renders nothing when there is no message, to avoid an empty red box', async () => {
    const { toJSON } = await render(<FormError />);

    expect(toJSON()).toBeNull();
  });

  it('renders the message when there is one', async () => {
    await render(<FormError message="Could not sign in." />);

    expect(await screen.findByText('Could not sign in.')).toBeOnTheScreen();
  });
});

// ---------------------------------------------------------------------------

describe('SettingsList', () => {
  it('only marks a row as a button when it actually does something', async () => {
    await render(
      <SettingsList
        rows={[
          { icon: 'person-outline', title: 'Account', onPress: jest.fn() },
          { icon: 'document-text-outline', title: 'Terms' },
        ]}
      />,
    );

    expect(await screen.findByLabelText('Account')).toBeEnabled();
    // A chevron on a dead row is a promise the app does not keep.
    expect(await screen.findByLabelText('Terms')).toBeDisabled();
  });

  it('fires the row handler', async () => {
    const onPress = jest.fn();
    await render(<SettingsList rows={[{ icon: 'log-out-outline', title: 'Sign out', onPress }]} />);

    await fireEvent.press(await screen.findByLabelText('Sign out'));

    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it('shows the optional heading, subtitle and value', async () => {
    await render(
      <SettingsList
        title="Account"
        rows={[
          {
            icon: 'call-outline',
            title: 'Phone',
            subtitle: 'Used for booking reminders',
            value: '+91 98xxx xxxxx',
          },
        ]}
      />,
    );

    expect(await screen.findByText('Account')).toBeOnTheScreen();
    expect(await screen.findByText('Used for booking reminders')).toBeOnTheScreen();
    expect(await screen.findByText('+91 98xxx xxxxx')).toBeOnTheScreen();
  });
});

// ---------------------------------------------------------------------------

describe('Stat', () => {
  it('shows the number and its caption', async () => {
    await render(<Stat label="Bookings" value={12} />);

    expect(await screen.findByText('12')).toBeOnTheScreen();
    expect(await screen.findByText('Bookings')).toBeOnTheScreen();
  });

  it('renders a string value such as an amount', async () => {
    await render(<Stat label="Earned" value="₹1,240" />);

    expect(await screen.findByText('₹1,240')).toBeOnTheScreen();
  });
});

// ---------------------------------------------------------------------------

describe('Button', () => {
  it('does not fire while loading, so a double tap cannot double charge', async () => {
    const onPress = jest.fn();
    await render(
      <Button loading onPress={onPress}>
        Pay
      </Button>,
    );

    await fireEvent.press(await screen.findByRole('button'));

    expect(onPress).not.toHaveBeenCalled();
  });

  it('does not fire when disabled', async () => {
    const onPress = jest.fn();
    await render(
      <Button disabled onPress={onPress}>
        Pay
      </Button>,
    );

    await fireEvent.press(await screen.findByRole('button'));

    expect(onPress).not.toHaveBeenCalled();
  });

  it('fires once pressed', async () => {
    const onPress = jest.fn();
    await render(<Button onPress={onPress}>Continue</Button>);

    await fireEvent.press(await screen.findByRole('button'));

    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it('still renders its label when it has no children, for icon-only buttons', async () => {
    await render(<Button icon="trash-outline" accessibilityLabel="Remove service" />);

    expect(await screen.findByLabelText('Remove service')).toBeOnTheScreen();
  });

  it('reports itself as busy while loading', async () => {
    await render(<Button loading>Saving</Button>);

    expect(await screen.findByRole('button')).toBeBusy();
  });
});

describe('Badge', () => {
  it('renders its label', async () => {
    await render(<Badge tone="success">Verified</Badge>);

    expect(await screen.findByText('Verified')).toBeOnTheScreen();
  });
});

describe('EmptyState', () => {
  it('explains what is missing and what to do about it', async () => {
    await render(
      <EmptyState
        icon="calendar-outline"
        title="No bookings yet"
        body="Book a shop to see it here."
      />,
    );

    expect(await screen.findByText('No bookings yet')).toBeOnTheScreen();
    expect(await screen.findByText('Book a shop to see it here.')).toBeOnTheScreen();
  });
});

// ---------------------------------------------------------------------------

describe('auth store', () => {
  beforeEach(async () => {
    await clearToken();
    useAuthStore.setState({ status: 'signed-out', token: null, user: null, error: null });
    jest.restoreAllMocks();
  });

  it('starts with no session', () => {
    const state = useAuthStore.getState();

    expect(state.user).toBeNull();
    expect(state.token).toBeNull();
    expect(currentToken()).toBeNull();
  });

  it('keeps the user and token together', async () => {
    const user = { id: 1, role: 'provider' } as never;
    await useAuthStore.getState().setSession('a-token', user);

    const state = useAuthStore.getState();
    expect(state.status).toBe('signed-in');
    expect(state.token).toBe('a-token');
    expect(state.user?.id).toBe(1);
  });

  it('persists the token so the session survives a restart', async () => {
    await useAuthStore.getState().setSession('a-token', { id: 1 } as never);

    expect(await readToken()).toBe('a-token');
  });

  it('forgets everything on sign out', async () => {
    await useAuthStore.getState().setSession('a-token', { id: 1 } as never);
    await useAuthStore.getState().signOut();

    const state = useAuthStore.getState();
    expect(state.status).toBe('signed-out');
    expect(state.token).toBeNull();
    expect(state.user).toBeNull();
    expect(await readToken()).toBeNull();
  });

  it('keeps the token but drops the user when /me/ is unreachable', async () => {
    await writeToken('a-token');
    jest
      .spyOn(global, 'fetch')
      .mockResolvedValue(new Response('gateway timeout', { status: 504 }));

    await useAuthStore.getState().bootstrap();

    const state = useAuthStore.getState();
    // Signing someone out because their train went into a tunnel loses whatever
    // they had typed. Keep the token and let them retry.
    expect(state.token).toBe('a-token');
    expect(state.user).toBeNull();
    expect(state.error).not.toBeNull();
  });

  it('signs out when the server rejects the stored token', async () => {
    await writeToken('stale');
    jest.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ error: { code: 'not_authenticated', message: 'No' } }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    await useAuthStore.getState().bootstrap();

    expect(useAuthStore.getState().token).toBeNull();
    expect(await readToken()).toBeNull();
  });

  it('restores the account on launch when the token is still good', async () => {
    await writeToken('good');
    jest.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ id: 7, role: 'customer' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    await useAuthStore.getState().bootstrap();

    const state = useAuthStore.getState();
    expect(state.status).toBe('signed-in');
    expect(state.user?.id).toBe(7);
  });

  it('goes straight to signed-out when there is no stored token', async () => {
    await useAuthStore.getState().bootstrap();

    expect(useAuthStore.getState().status).toBe('signed-out');
  });

  it('clears a stored error', () => {
    useAuthStore.setState({ error: 'Something went wrong' });
    useAuthStore.getState().clearError();

    expect(useAuthStore.getState().error).toBeNull();
  });
});

// ---------------------------------------------------------------------------

describe('query client', () => {
  const query = queryClient.getDefaultOptions().queries ?? {};

  it('retries a dropped connection before showing an error', () => {
    expect(query.retry).toBeInstanceOf(Function);
    // Two tries is enough for a phone on a bad signal, and no more: a user
    // staring at a spinner for ten seconds has already given up.
    expect((query.retry as (n: number, e: unknown) => boolean)(0, new Error('network'))).toBe(true);
    expect((query.retry as (n: number, e: unknown) => boolean)(2, new Error('network'))).toBe(
      false,
    );
  });

  it('does not retry a 4xx, because the request is wrong and will stay wrong', () => {
    expect((query.retry as (n: number, e: unknown) => boolean)(0, new ApiError('x', 400, 'y'))).toBe(
      false,
    );
  });

  it('does retry a 5xx', () => {
    expect((query.retry as (n: number, e: unknown) => boolean)(0, new ApiError('x', 503, 'y'))).toBe(
      true,
    );
  });

  it('never refetches a window the user is already reading', () => {
    expect(query.refetchOnWindowFocus).toBe(false);
  });

  it('does not retry mutations, which are not idempotent', () => {
    expect(queryClient.getDefaultOptions().mutations?.retry).toBe(false);
  });
});
