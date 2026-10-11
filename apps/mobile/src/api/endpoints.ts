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
  OrderQuote,
  PriceBand,
  Product,
  ProductCategory,
  ProductOrder,
  LedgerEntry,
  Payout,
  ProviderBalance,
  Withdrawal,
  ShopProduct,
  Quote,
  Review,
  ReviewPage,
  Service,
  ServicePriceEntry,
  ServiceTypeOption,
  User,
  WorkingHours,
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

  /** Typical prices per shop type, aggregated across the platform. */
  priceBands: () =>
    api.get<{ bands: PriceBand[]; minimum_sample: number }>('/providers/prices/'),

  /** Median price per service name, for names several shops offer. */
  servicePrices: () =>
    api.get<{ services: ServicePriceEntry[] }>('/providers/prices/services/'),

  myShop: () => api.get<ProviderSelf>('/providers/me/'),

  updateShop: (body: Record<string, unknown>) => api.patch<ProviderSelf>('/providers/me/', body),

  myServices: () => api.get<Service[]>('/providers/me/services/'),

  createService: (body: Partial<Service>) =>
    api.post<Service>('/providers/me/services/', body),

  updateService: (id: number, body: Partial<Service>) =>
    api.patch<Service>(`/providers/me/services/${id}/`, body),

  deleteService: (id: number) => api.delete(`/providers/me/services/${id}/`),

  hours: () => api.get<WorkingHours[]>('/providers/me/hours/'),

  saveHours: (days: {
    weekday: number;
    is_closed: boolean;
    opens_at: string;
    closes_at: string;
  }[]) => api.put<WorkingHours[]>('/providers/me/hours/', { days }),

  /**
   * The switch that decides whether a shop can be booked at all.
   *
   * Separate from `updateShop` because turning this off is the single most
   * consequential thing a provider does from the app, and it deserves its own
   * explicit call rather than a field inside a big settings patch.
   */
  setAcceptingBookings: (isAcceptingBookings: boolean) =>
    api.post<ProviderSelf>('/providers/me/accepting-bookings/', {
      is_accepting_bookings: isAcceptingBookings,
    }),

  myPayout: () => api.get<Payout>('/providers/me/payout/'),

  balance: () => api.get<ProviderBalance>('/providers/me/balance/'),

  ledger: (params: { page?: number } = {}) =>
    api.get<{ count: number; results: LedgerEntry[] }>('/providers/me/ledger/', params as QueryParams),

  /**
   * Ask for money to be sent to the bank.
   *
   * Amount is optional and defaults to everything cleared, because that is what
   * providers want almost every time.
   */
  withdraw: (amount?: number) =>
    api.post<{ withdrawal: Withdrawal; balance: ProviderBalance }>(
      '/providers/me/withdraw/',
      amount ? { amount } : {},
    ),

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

  /**
   * Record what was taken at the counter.
   *
   * Not a transition: taking the money and finishing the appointment are
   * separate decisions. A customer who paid and then walked out has still been
   * paid.
   */
  collect: (reference: string, body?: { amount?: number; method?: 'cash' | 'upi' | 'card'; note?: string }) =>
    api.post<Booking>(`/bookings/${reference}/collect/`, body ?? {}),
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

export const productsApi = {
  browse: (params: { category?: string; brand?: string; search?: string } = {}) =>
    api.get<{ count: number; results: Product[] }>('/products/', params as QueryParams),

  popular: () => api.get<Product[]>('/products/popular/'),

  categories: () => api.get<{ value: ProductCategory; label: string }[]>('/products/types/'),

  detail: (id: number) => api.get<Product>(`/products/${id}/`),

  /** What one shop is actually selling, with that shop's stock. */
  shopShelf: (providerId: number, params: { search?: string; category?: string } = {}) =>
    api.get<ShopProduct[]>(`/products/shops/${providerId}/`, params as QueryParams),

  myShelf: () => api.get<{ id: number; product: Product; quantity: number; is_available: boolean }[]>('/products/me/inventory/'),

  setStock: (productId: number, quantity: number, isAvailable = true) =>
    api.post('/products/me/inventory/', {
      product: productId,
      quantity,
      is_available: isAvailable,
    }),

  shopOrders: (params: { status?: string } = {}) =>
    api.get<{ count: number; results: ProductOrder[] }>('/products/me/shop-orders/', params as QueryParams),
};

export const ordersApi = {
  my: (params: { status?: string } = {}) =>
    api.get<{ count: number; results: ProductOrder[] }>('/products/me/orders/', params as QueryParams),

  quote: (body: { provider: number; items: { product: number; quantity: number }[] }) =>
    api.post<OrderQuote>('/products/orders/quote/', body),

  create: (body: { provider: number; items: { product: number; quantity: number }[]; notes?: string }) =>
    api.post<ProductOrder>('/products/orders/new/', body),

  get: (reference: string) => api.get<ProductOrder>(`/products/orders/${reference}/`),

  act: (reference: string, action: 'cancel' | 'ready' | 'collect') =>
    api.post<ProductOrder>(`/products/orders/${reference}/action/`, { action }),
};

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