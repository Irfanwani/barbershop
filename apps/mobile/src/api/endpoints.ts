/**
 * Every server call the app makes, in one file.
 *
 * Screens import from here rather than building URLs. When an endpoint moves,
 * this is the only file that changes.
 */

import { api, ApiError, type QueryParams } from '@/api/client';
import type {
  AuthResponse,
  Availability,
  Booking,
  BookingPage,
  BookingStatus,
  CustomerProfile,
  Payment,
  ProviderDetail,
  ProviderPage,
  ProviderSelf,
  Payout,
  Quote,
  Review,
  ReviewPage,
  Service,
  ServiceTypeOption,
  User,
} from '@/types/api';

export const authApi = {
  register: (body: {
    username: string;
    email: string;
    password: string;
    role: string;
  }) => api.post<AuthResponse>('/auth/register/', body),

  login: (body: { identifier: string; password: string }) =>
    api.post<AuthResponse>('/auth/login/', body),

  logout: () => api.post<void>('/auth/logout/'),

  logoutAll: () => api.post<void>('/auth/logout-all/'),

  verifyEmail: (code: string) =>
    api.post<{ verified: boolean; message: string; user: User }>('/auth/verify-email/', {
      code,
    }),

  resendVerification: () =>
    api.post<{ verified: boolean; message: string }>('/auth/resend-verification/'),

  requestPasswordReset: (email: string) =>
    api.post<{ sent: boolean; message: string }>('/auth/password-reset/request/', { email }),

  confirmPasswordReset: (body: { email: string; code: string; new_password: string }) =>
    api.post<AuthResponse & { password_changed: boolean }>(
      '/auth/password-reset/confirm/',
      body,
    ),
};

export const meApi = {
  get: () => api.get<User>('/me/'),

  update: (body: Partial<Pick<User, 'first_name' | 'last_name' | 'phone'>> & {
    avatar?: { uri: string };
    avatarName?: string;
    avatarType?: string;
  }) => {
    // Multipart: the endpoint accepts form fields directly and sets the
    // boundary itself.
    const form = new FormData();
    for (const [key, value] of Object.entries(body)) {
      if (value === undefined) continue;
      if (key === 'avatar' && typeof value === 'object' && value !== null && 'uri' in value) {
        const file = value as { uri: string };
        form.append('avatar', {
          uri: file.uri,
          name: body.avatarName ?? 'avatar.jpg',
          type: body.avatarType ?? 'image/jpeg',
        } as unknown as Blob);
      } else {
        form.append(key, String(value));
      }
    }
    return api.patch<User>('/me/', form);
  },

  changePassword: (body: { current_password: string; new_password: string }) =>
    api.post<{ message: string }>('/me/password/', body),

  customerProfile: () => api.get<CustomerProfile>('/me/profile/'),

  saveCustomerProfile: (body: Record<string, unknown>) => {
    const form = new FormData();
    for (const [key, value] of Object.entries(body)) {
      if (value === undefined || value === null) continue;
      if (typeof value === 'object' && 'uri' in (value as object)) {
        const file = value as { uri: string; name?: string; type?: string };
        form.append(key, {
          uri: file.uri,
          name: file.name ?? 'photo.jpg',
          type: file.type ?? 'image/jpeg',
        } as unknown as Blob);
      } else {
        form.append(key, String(value));
      }
    }
    return api.put<CustomerProfile>('/me/profile/', form);
  },

  shop: () => api.get<ProviderSelf>('/me/shop/'),

  saveShop: (body: Record<string, unknown>) => {
    const form = new FormData();
    for (const [key, value] of Object.entries(body)) {
      if (value === undefined || value === null) continue;
      if (typeof value === 'object' && 'uri' in (value as object)) {
        const file = value as { uri: string; name?: string; type?: string };
        form.append(key, {
          uri: file.uri,
          name: file.name ?? 'photo.jpg',
          type: file.type ?? 'image/jpeg',
        } as unknown as Blob);
      } else {
        form.append(key, String(value));
      }
    }
    return api.put<ProviderSelf>('/me/shop/', form);
  },

  createShop: (body: Record<string, unknown>) => {
    const form = new FormData();
    for (const [key, value] of Object.entries(body)) {
      if (value === undefined || value === null) continue;
      if (typeof value === 'object' && 'uri' in (value as object)) {
        const file = value as { uri: string; name?: string; type?: string };
        form.append(key, {
          uri: file.uri,
          name: file.name ?? 'photo.jpg',
          type: file.type ?? 'image/jpeg',
        } as unknown as Blob);
      } else {
        form.append(key, String(value));
      }
    }
    return api.post<ProviderSelf>('/me/shop/create/', form);
  },

  registerPushToken: (token: string, platform: string) =>
    api.post('/me/push-tokens/', { token, platform }),

  clearPushTokens: () => api.delete('/me/push-tokens/clear/'),

  loginHistory: () => api.get('/me/login-history/'),

  deleteAccount: () => api.delete('/me/'),
};

export interface ProviderSearch {
  lat?: number;
  lng?: number;
  radius_km?: number;
  service_type?: string;
  services?: string[];
  open_now?: boolean;
  min_rating?: number;
  page?: number;
  page_size?: number;
}

export const providersApi = {
  search: (params: ProviderSearch, signal?: AbortSignal) =>
    api.get<ProviderPage>('/providers/', params as QueryParams, signal),

  get: (id: number, params?: { lat?: number; lng?: number }) =>
    api.get<ProviderDetail>(`/providers/${id}/`, params as QueryParams),

  serviceTypes: () => api.get<ServiceTypeOption[]>('/providers/types/'),

  myShop: () => api.get<ProviderSelf>('/providers/me/'),

  updateShop: (body: Record<string, unknown>) => api.patch<ProviderSelf>('/providers/me/', body),

  myServices: () => api.get<Service[]>('/providers/me/services/'),

  createService: (body: Partial<Service>) =>
    api.post<Service>('/providers/me/services/', body),

  updateService: (id: number, body: Partial<Service>) =>
    api.patch<Service>(`/providers/me/services/${id}/`, body),

  deleteService: (id: number) => api.delete(`/providers/me/services/${id}/`),

  myPayout: () => api.get<Payout>('/providers/me/payout/'),

  savePayout: (body: Record<string, string>) =>
    api.put<Payout>('/providers/me/payout/', body),

  availability: (id: number, days = 14) =>
    api.get<Availability>(`/providers/${id}/availability/`, { days }),
};

export const bookingsApi = {
  list: (params?: { status?: string; upcoming?: boolean; past?: boolean; page?: number }) =>
    api.get<BookingPage>('/bookings/', params as QueryParams),

  get: (reference: string) => api.get<Booking>(`/bookings/${reference}/`),

  quote: (body: { provider: number; services: number[]; starts_at: string }) =>
    api.post<Quote>('/bookings/quote/', body),

  create: (body: { provider: number; services: number[]; starts_at: string; notes?: string }) =>
    api.post<Booking>('/bookings/new/', body),

  cancel: (reference: string, reason = '') =>
    api.post<Booking>(`/bookings/${reference}/cancel/`, { reason }),

  transition: (reference: string, action: 'accept' | 'decline' | 'complete' | 'no-show') =>
    api.post<Booking>(`/bookings/${reference}/${action}/`),
};

export const reviewsApi = {
  list: (params?: { provider?: number; mine?: boolean; rating?: number; page?: number }) =>
    api.get<ReviewPage>('/reviews/', params as QueryParams),

  create: (body: {
    provider: number;
    rating: number;
    comment?: string;
    booking?: number | null;
  }) => api.post<Review>('/reviews/new/', body),

  remove: (id: number) => api.delete(`/reviews/${id}/`),

  reply: (id: number, provider_reply: string) =>
    api.post<Review>(`/reviews/${id}/reply/`, { provider_reply }),
};

export const paymentsApi = {
  createOrder: (bookingReference: string) =>
    api.post<{
      payment: Payment;
      razorpay: { key_id: string; order_id: string; amount: number; currency: string };
      amount_display: string;
    }>('/payments/orders/', { booking: bookingReference }),

  verify: (body: {
    razorpay_order_id: string;
    razorpay_payment_id: string;
    razorpay_signature: string;
  }) => api.post<Payment>('/payments/verify/', body),

  get: (orderId: string) => api.get<Payment>(`/payments/${orderId}/`),
};

/** Which screen the app should open, given the account's state. */
export type Destination =
  | 'welcome'
  | 'login'
  | 'verify-email'
  | 'onboarding'
  | 'customer'
  | 'provider';

export function destinationFor(user: User | null, seenWelcome: boolean): Destination {
  if (!user) return seenWelcome ? 'login' : 'welcome';
  if (!user.is_verified) return 'verify-email';
  if (!user.onboarding_complete) return 'onboarding';
  return user.role === 'provider' ? 'provider' : 'customer';
}

export const BOOKING_STATUS_LABELS: Record<BookingStatus, string> = {
  pending_payment: 'Awaiting payment',
  awaiting_confirmation: 'Awaiting confirmation',
  confirmed: 'Confirmed',
  completed: 'Completed',
  cancelled_by_customer: 'Cancelled',
  cancelled_by_provider: 'Cancelled by the shop',
  no_show: 'No show',
  refunded: 'Refunded',
};

export { ApiError };