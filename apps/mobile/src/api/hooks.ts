/**
 * Query and mutation hooks.
 *
 * Screens call these instead of touching `api` directly. Two things fall out of
 * that: invalidating a booking refreshes the provider's availability and the
 * review summary without anyone remembering to, and no screen decides on its own
 * what "up to date" means.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from '@tanstack/react-query';

import {
  bookingsApi,
  meApi,
  ordersApi,
  paymentsApi,
  productsApi,
  providersApi,
  reviewsApi,
  type ProviderSearch,
} from '@/api/endpoints';
import { keys } from '@/lib/query-client';
import type {
  Availability,
  Booking,
  BookingPage,
  CustomerProfile,
  ProviderPage,
  ProviderSelf,
  Payout,
  ReviewPage,
  Service,
  User,
} from '@/types/api';

// ---------------------------------------------------------------------------
// account
// ---------------------------------------------------------------------------

export function useMe(options?: Partial<UseQueryOptions<User>>) {
  return useQuery({ queryKey: keys.me, queryFn: meApi.get, ...options });
}

export function useUpdateMe() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: meApi.update,
    onSuccess: (user) => {
      client.setQueryData(keys.me, user);
    },
  });
}

export function useDeleteAccount() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: meApi.deleteAccount,
    onSuccess: () => {
      client.clear();
    },
  });
}

export function useCustomerProfile() {
  return useQuery({
    queryKey: keys.customerProfile,
    queryFn: meApi.customerProfile,
    // A customer profile exists from the moment they sign in; the endpoint
    // returns an empty shape until they fill it in, so there is nothing to
    // re-fetch on every focus.
    staleTime: 5 * 60_000,
  });
}

export function useSaveCustomerProfile() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: meApi.saveCustomerProfile,
    onSuccess: (profile: CustomerProfile) => {
      client.setQueryData(keys.customerProfile, profile);
      // Saving a location changes what "near me" means, so the browse list and
      // the signed-in account both need to know.
      client.invalidateQueries({ queryKey: ['providers', 'list'] });
      void client.invalidateQueries({ queryKey: keys.me });
    },
  });
}

export function useLoginHistory() {
  return useQuery({ queryKey: ['me', 'login-history'], queryFn: meApi.loginHistory });
}

// ---------------------------------------------------------------------------
// providers
// ---------------------------------------------------------------------------

export function useProviderSearch(params: ProviderSearch) {
  return useQuery({
    queryKey: keys.providers(params),
    queryFn: ({ signal }) => providersApi.search(params, signal),
    // Location changes as the user moves; a short window keeps the list honest
    // without hammering the API on every render.
    staleTime: 60_000,
  });
}

export function useProvider(id: number | null, origin?: { lat: number; lng: number }) {
  return useQuery({
    queryKey: keys.provider(id ?? 'none'),
    queryFn: () => providersApi.get(id as number, origin),
    enabled: id !== null,
  });
}

export function useServiceTypes() {
  return useQuery({
    queryKey: keys.serviceTypes,
    queryFn: providersApi.serviceTypes,
    staleTime: Infinity,
  });
}

export function useMyShop() {
  return useQuery({ queryKey: keys.shop, queryFn: providersApi.myShop, retry: false });
}

export function useSaveShop() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: providersApi.updateShop,
    onSuccess: (shop: ProviderSelf) => {
      client.setQueryData(keys.shop, shop);
      client.invalidateQueries({ queryKey: keys.services });
      void client.invalidateQueries({ queryKey: keys.me });
    },
  });
}

export function useCreateShop() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: meApi.createShop,
    onSuccess: () => {
      client.removeQueries({ queryKey: keys.shop });
      void client.invalidateQueries({ queryKey: keys.me });
    },
  });
}

export function useMyHours() {
  return useQuery({
    queryKey: keys.hours,
    queryFn: providersApi.hours,
    // The hours are the source of truth for whether anything is bookable, so a
    // stale copy means a provider sets Sunday's hours against last week's.
    staleTime: 0,
  });
}

export function useSaveHours() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: providersApi.saveHours,
    onSuccess: (days) => {
      client.setQueryData(keys.hours, days);
      // Opening hours decide which slots exist, so the calendar and the shop's
      // own summary are both now wrong.
      void client.invalidateQueries({ queryKey: ['providers'] });
      void client.invalidateQueries({ queryKey: ['providers', 'detail'] });
    },
  });
}

export function useSetAcceptingBookings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: providersApi.setAcceptingBookings,
    onSuccess: (shop: ProviderSelf) => {
      client.setQueryData(keys.shop, shop);
      // A shop that just closed must disappear from the browse list.
      void client.invalidateQueries({ queryKey: ['providers'] });
      void client.invalidateQueries({ queryKey: ['providers', 'detail'] });
      void client.invalidateQueries({ queryKey: keys.me });
    },
  });
}

export function useMyServices() {
  return useQuery({ queryKey: keys.services, queryFn: providersApi.myServices });
}

function useInvalidateServices() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: keys.services });
    void client.invalidateQueries({ queryKey: keys.shop });
  };
}

export function useCreateService() {
  const invalidate = useInvalidateServices();
  return useMutation({ mutationFn: providersApi.createService, onSuccess: invalidate });
}

export function useUpdateService() {
  const invalidate = useInvalidateServices();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: Partial<Service> }) =>
      providersApi.updateService(id, body),
    onSuccess: invalidate,
  });
}

export function useDeleteService() {
  const invalidate = useInvalidateServices();
  return useMutation({
    mutationFn: providersApi.deleteService,
    onSuccess: invalidate,
  });
}

export function useMyPayout() {
  return useQuery({ queryKey: keys.payout, queryFn: providersApi.myPayout, retry: false });
}

export function useSavePayout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: providersApi.savePayout,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.payout });
      void client.invalidateQueries({ queryKey: keys.me });
    },
  });
}

export function useAvailability(id: number | null, days = 14) {
  return useQuery({
    queryKey: keys.availability(id ?? 'none', days),
    queryFn: () => providersApi.availability(id as number, days),
    enabled: id !== null,
    staleTime: 30_000,
  });
}

// ---------------------------------------------------------------------------
// bookings
// ---------------------------------------------------------------------------

export function useBookings(params?: { upcoming?: boolean; past?: boolean; status?: string }) {
  return useQuery({
    queryKey: keys.bookings(params),
    queryFn: () => bookingsApi.list(params),
  });
}

export function useBooking(reference: string | null) {
  return useQuery({
    queryKey: keys.booking(reference as string),
    queryFn: () => bookingsApi.get(reference as string),
    enabled: Boolean(reference),
  });
}

/** Anything that moves a booking also moves the calendar it sits in. */
function useInvalidateBookings() {
  const client = useQueryClient();
  return (reference?: string) => {
    if (reference) void client.invalidateQueries({ queryKey: keys.booking(reference) });
    void client.invalidateQueries({ queryKey: ['bookings'] });
    void client.invalidateQueries({ queryKey: ['providers', 'availability'] });
    void client.invalidateQueries({ queryKey: ['reviews', 'list'] });
  };
}

export function useQuote() {
  return useMutation({
    mutationFn: bookingsApi.quote,
    // Prices are stable, but a quote taken twenty minutes ago may be stale.
    gcTime: 2 * 60_000,
  });
}

export function useCreateBooking() {
  const invalidate = useInvalidateBookings();
  return useMutation({
    mutationFn: bookingsApi.create,
    onSuccess: (booking: Booking) => invalidate(booking.reference),
  });
}

export function useCancelBooking() {
  const invalidate = useInvalidateBookings();
  return useMutation({
    mutationFn: ({ reference, reason }: { reference: string; reason?: string }) =>
      bookingsApi.cancel(reference, reason ?? ''),
    onSuccess: (booking: Booking) => invalidate(booking.reference),
  });
}

export function useTransitionBooking() {
  const invalidate = useInvalidateBookings();
  return useMutation({
    mutationFn: ({
      reference,
      action,
    }: {
      reference: string;
      action: 'accept' | 'decline' | 'complete' | 'no-show';
    }) => bookingsApi.transition(reference, action),
    onSuccess: (booking: Booking) => invalidate(booking.reference),
  });
}

// ---------------------------------------------------------------------------
// reviews
// ---------------------------------------------------------------------------

export function useReviews(params?: { provider?: number; mine?: boolean; rating?: number }) {
  return useQuery({ queryKey: keys.reviews(params), queryFn: () => reviewsApi.list(params) });
}

export function useCreateReview() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: reviewsApi.create,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['reviews'] });
      // The provider's cached rating changes, which the browse list shows.
      void client.invalidateQueries({ queryKey: ['providers', 'list'] });
      void client.invalidateQueries({ queryKey: ['bookings'] });
    },
  });
}

export function useReplyToReview() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reply }: { id: number; reply: string }) => reviewsApi.reply(id, reply),
    onSuccess: () => client.invalidateQueries({ queryKey: ['reviews'] }),
  });
}

// ---------------------------------------------------------------------------
// payments
// ---------------------------------------------------------------------------

export function useCreateOrder() {
  return useMutation({ mutationFn: paymentsApi.createOrder });
}

export function useVerifyPayment() {
  const invalidate = useInvalidateBookings();
  return useMutation({
    mutationFn: paymentsApi.verify,
    onSuccess: () => invalidate(),
  });
}

export type { BookingPage, ProviderPage, ReviewPage, Availability, Payout, User };
// ---------------------------------------------------------------------------
// Products and orders
// ---------------------------------------------------------------------------

export function useProducts(params: { category?: string; brand?: string; search?: string }) {
  return useQuery({
    queryKey: keys.products(params),
    queryFn: () => productsApi.browse(params),
  });
}

export function usePopularProducts() {
  return useQuery({ queryKey: keys.popular, queryFn: productsApi.popular });
}

export function useProductCategories() {
  // The category list is fixed by the API version; no need to refetch it.
  return useQuery({
    queryKey: keys.categories,
    queryFn: productsApi.categories,
    staleTime: Infinity,
  });
}

export function useShopShelf(
  providerId: number | null,
  params: { search?: string; category?: string } = {},
) {
  return useQuery({
    queryKey: keys.shopShelf(providerId ?? 'none', params),
    queryFn: () => productsApi.shopShelf(providerId as number, params),
    enabled: providerId !== null,
  });
}

export function useMyShelf() {
  return useQuery({ queryKey: keys.myShelf, queryFn: productsApi.myShelf });
}

export function useSetStock() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ product, quantity }: { product: number; quantity: number }) =>
      productsApi.setStock(product, quantity),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.myShelf });
    },
  });
}

export function useMyOrders(params: { status?: string } = {}) {
  return useQuery({ queryKey: keys.myOrders(params), queryFn: () => ordersApi.my(params) });
}

export function useShopOrders(params: { status?: string } = {}) {
  return useQuery({
    queryKey: keys.shopOrders(params),
    queryFn: () => productsApi.shopOrders(params),
  });
}

export function useOrder(reference: string | null) {
  return useQuery({
    queryKey: keys.order(reference ?? 'none'),
    queryFn: () => ordersApi.get(reference as string),
    enabled: Boolean(reference),
  });
}

export function useOrderQuote(
  providerId: number | null,
  basket: { product: number; quantity: number }[],
) {
  return useQuery({
    // Keyed on the basket too, not just the shop: the quote changes when the
    // quantities do, and caching it per-shop would show a stale total.
    queryKey: [...keys.orderQuote(providerId ?? 0), basket],
    queryFn: () => ordersApi.quote({ provider: providerId as number, items: basket }),
    // Nothing to quote for an empty basket; the server could only say so.
    enabled: providerId !== null && basket.length > 0,
  });
}

export function useCreateProductOrder() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ordersApi.create,
    onSuccess: (order) => {
      void client.invalidateQueries({ queryKey: ['orders'] });
      void client.invalidateQueries({ queryKey: ['products'] });
      client.setQueryData(keys.order(order.reference), order);
    },
  });
}

export function useOrderAction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      reference,
      action,
    }: {
      reference: string;
      action: 'cancel' | 'ready' | 'collect';
    }) => ordersApi.act(reference, action),
    onSuccess: (order) => {
      client.setQueryData(keys.order(order.reference), order);
      void client.invalidateQueries({ queryKey: ['orders'] });
      // Cancelling puts the units back on the shelf.
      void client.invalidateQueries({ queryKey: ['products'] });
    },
  });
}
