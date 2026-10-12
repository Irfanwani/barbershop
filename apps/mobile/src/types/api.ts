/**
 * The shapes the API returns.
 *
 * Hand-written against `services/api/docs/openapi.yml` rather than generated.
 * Generated types would be more complete and would also churn on every backend
 * tweak; these cover what the screens actually read, so a field the app does not
 * use is not a reason to touch the app.
 */

export type Role = 'customer' | 'provider';

export type ServiceType =
  | 'barbershop'
  | 'hair_salon'
  | 'beauty_salon'
  | 'full_service_salon'
  | 'spa'
  | 'massage'
  | 'other';

export type BookingStatus =
  | 'pending_payment'
  | 'awaiting_confirmation'
  | 'confirmed'
  | 'completed'
  | 'cancelled_by_customer'
  | 'cancelled_by_provider'
  | 'no_show'
  | 'refunded';

export type PaymentStatus = 'created' | 'attempted' | 'captured' | 'failed' | 'refunded';

/** Every error the API returns has exactly this shape. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: Record<string, string[]> | string[] | null;
  };
}

export interface User {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  display_name: string;
  role: Role;
  is_verified: boolean;
  verified_at: string | null;
  avatar: string | null;
  phone: string;
  timezone_name: string;
  has_customer_profile: boolean;
  has_provider_profile: boolean;
  has_payout: boolean;
  service_count: number;
  onboarding_complete: boolean;
}

export interface AuthResponse {
  token: string;
  user: User;
  verification_required?: boolean;
  verification_email_sent?: boolean;
  password_changed?: boolean;
}

export interface Coordinates {
  latitude: number;
  longitude: number;
}

export interface CustomerProfile {
  about: string;
  address: string;
  photo: string | null;
  coords: Coordinates | null;
  has_location: boolean;
  preferred_service_type: string;
  updated_at: string;
}

export interface Service {
  id: number;
  name: string;
  description: string;
  /** Paise. 25000 is ₹250.00. */
  price: number;
  price_display: string;
  duration_minutes: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Payout {
  business_name: string;
  business_type: string;
  beneficiary_name: string;
  account_type: string;
  account_number_masked?: string;
  ifsc_code_masked?: string;
  verification_status: string;
  is_verified?: boolean;
  rejection_reason?: string;
  razorpay_account_id?: string;
  updated_at?: string;
  payout_registered: boolean;
  message?: string;
}

export interface ProviderSummary {
  id: number;
  display_name: string;
  service_type: ServiceType;
  photo: string | null;
  rating_average: string;
}

export interface ProviderListItem extends ProviderSummary {
  /** Whether the shop is currently taking bookings at all. */
  is_accepting_bookings: boolean;
  /** Whether *this* customer has saved the shop. */
  is_saved?: boolean;
  description: string;
  service_type_label: string;
  cover_photo: string | null;
  address: string;
  approximate_location: (Coordinates & { precision_meters: number }) | null;
  is_open_now: boolean;
  next_available: string | null;
  opening_time: string;
  closing_time: string;
  employee_count: number;
  requires_approval: boolean;
  rating_count: number;
  starting_price_display: string | null;
  starting_price?: number | null;
  owner: { id: number; username: string; display_name: string };
  created_at: string;
  /** Only present when the search had an origin. */
  distance_km?: number;
}

export interface ProviderDetail extends ProviderListItem {
  services: Service[];
  active_service_count: number;
  accepts_bookings: boolean;
  contact_phone?: string;
  slot_interval_minutes?: number;
  distance_km?: number;
}

export interface ProviderSelf {
  id: number;
  display_name: string;
  is_accepting_bookings: boolean;
  description: string;
  service_type: ServiceType;
  photo: string | null;
  cover_photo: string | null;
  address: string;
  coords: Coordinates;
  contact_phone: string;
  employee_count: number;
  opening_time: string;
  closing_time: string;
  slot_interval_minutes: number;
  requires_approval: boolean;
  rating_average: string;
  rating_count: number;
  starting_price_display: string | null;
  services: Service[];
  owner: { id: number; username: string; display_name: string };
  payout_registered: boolean;
  created_at: string;
  updated_at: string;
}

/**
 * One weekday of a provider's opening hours.
 *
 * `weekday` follows Django's convention: 0 is Monday, 6 is Sunday. Using
 * Sunday as 0 would silently shift every day by one, which is the kind of bug
 * that shows up as "closed on the wrong day" and takes a week to trace.
 */
/**
 * Someone who works at a shop.
 *
 * `is_placeholder` marks a row the headcount migration created: real capacity,
 * no name yet. The app says so rather than showing "Staff member 3" as though
 * someone had chosen it.
 */
/** A waitlist entry: "tell me when something frees up". */
export interface WaitlistEntry {
  id: number;
  provider: number;
  provider_name: string;
  service: number;
  service_name: string;
  staff: number | null;
  staff_name: string | null;
  window_start: string;
  window_end: string;
  status: 'waiting' | 'offered' | 'booked' | 'declined' | 'left';
  created_at: string;
}

/** A slot being held for this customer, with the countdown attached. */
export interface WaitlistOffer {
  id: number;
  shop_name: string;
  service_name: string;
  staff_name: string | null;
  starts_at: string;
  ends_at: string;
  status: 'pending' | 'accepted' | 'declined' | 'expired';
  expires_at: string;
  seconds_left: number;
  can_accept: boolean;
}

/**
 * A shop this customer saved.
 *
 * Carries the live shop fields, not a snapshot: a saved shop shows its
 * current price and whether it is still taking bookings.
 */
export interface SavedShop {
  id: number;
  note: string;
  created_at: string;
  provider: ProviderListItem;
}

export interface StaffMember {
  id: number;
  name: string;
  bio: string;
  photo: string | null;
  is_active: boolean;
  is_placeholder: boolean;
  is_open_today: boolean;
  hours: {
    weekday: number;
    weekday_label: string;
    is_closed: boolean;
    opens_at: string;
    closes_at: string;
  }[];
}

export interface WorkingHours {
  id: number;
  weekday: number;
  weekday_label: string;
  is_closed: boolean;
  opens_at: string;
  closes_at: string;
}

export type ProductCategory = 'haircare' | 'tools' | 'styling' | 'skincare' | 'other';

export interface Product {
  id: number;
  name: string;
  description: string;
  brand: string;
  category: ProductCategory;
  price: number;
  price_display: string;
  compare_at_price: number | null;
  compare_at_price_display: string | null;
  is_discounted: boolean;
  photo: string | null;
  is_active: boolean;
}

export interface ShopProduct {
  id: number;
  product: Product;
  quantity: number;
  is_in_stock: boolean;
}

export interface PriceBand {
  service_type: string;
  service_type_label: string;
  sample_size: number;
  minimum: number | null;
  minimum_display: string | null;
  maximum: number | null;
  maximum_display: string | null;
  average: number | null;
  average_display: string | null;
  median: number | null;
  median_display: string | null;
  p25: number | null;
  p25_display: string | null;
  p75: number | null;
  p75_display: string | null;
  /** Fewer shops than the server is comfortable with. Say so rather than pretending. */
  is_thin: boolean;
}

export interface ServicePriceEntry {
  name: string;
  sample_size: number;
  median: number | null;
  median_display: string | null;
  minimum: number | null;
  minimum_display: string | null;
  maximum: number | null;
  maximum_display: string | null;
}

/**
 * What a provider is owed.
 *
 * Derived server-side from an append-only ledger, so every figure here can be
 * explained line by line on the earnings screen.
 */
export interface ProviderBalance {
  pending: number;
  pending_display: string;
  cleared: number;
  cleared_display: string;
  paid_out: number;
  paid_out_display: string;
  total: number;
  total_display: string;
}

/** One row of "what each service earns". */
export interface ServiceEarnings {
  name: string;
  bookings: number;
  completed: number;
  gross: number;
  gross_display: string;
  earnings: number;
  earnings_display: string;
}

/**
 * The counts behind a period, and how they compare with the one before it.
 *
 * `percent` is null when there is nothing to compare against. It is not 100 or
 * Infinity: a shop going from nothing to something has not grown by a
 * percentage, and rendering it as one is how a dashboard starts lying.
 */
export interface AnalyticsChange {
  now: number;
  before: number;
  difference: number;
  percent: number | null;
}

export interface PeriodMetrics {
  bookings: number;
  completed: number;
  cancelled: number;
  no_shows: number;
  upcoming: number;
  revenue_earned: number;
  revenue_earned_display: string;
  platform_fees: number;
  platform_fees_display: string;
  tips: number;
  tips_display: string;
  no_show_rate: number;
  rebooking_rate: number;
  rebooking_customers: number;
  eligible_customers: number;
  utilisation: number;
  booked_minutes: number;
  available_minutes: number;
  per_service: ServiceEarnings[];
}

export interface ProviderAnalytics {
  period: {
    from: string;
    to: string;
    days: number;
    previous_from: string;
    previous_to: string;
  };
  available_days: number[];
  current: PeriodMetrics;
  previous: PeriodMetrics;
  changes: Record<string, AnalyticsChange>;
}

export interface LedgerEntry {
  id: number;
  kind: string;
  status: 'pending' | 'cleared' | 'paid_out' | 'voided';
  amount: number;
  amount_display: string;
  reference: string;
  description: string;
  created_at: string;
}

export interface Withdrawal {
  amount: number;
  reference: string;
  transfer_id: string;
  status: string;
}

export interface BasketLine {
  product: number;
  quantity: number;
}

export interface OrderQuote {
  lines: {
    product: number;
    name: string;
    unit_price: number;
    quantity: number;
    line_total: number;
  }[];
  subtotal: number;
  platform_fee: number;
  total: number;
  total_display: string;
  currency: string;
}

export type OrderStatus = 'pending' | 'paid' | 'ready' | 'collected' | 'cancelled' | 'refunded';

export interface ProductOrder {
  id: number;
  reference: string;
  provider: { id: number; display_name: string; address: string };
  status: OrderStatus;
  lines: { product: number; name: string; unit_price: number; quantity: number; line_total: number }[];
  subtotal: number;
  platform_fee: number;
  total: number;
  total_display: string;
  currency: string;
  notes: string;
  paid_at: string | null;
  collected_at: string | null;
  cancelled_at: string | null;
  can_be_paid: boolean;
  can_be_collected: boolean;
  created_at: string;
}

export interface BookingItem {
  id: number;
  service: number | null;
  name: string;
  unit_price: number;
  unit_price_display: string;
  quantity: number;
  duration_minutes: number;
  line_total: number;
}

export interface Booking {
  id: number;
  reference: string;
  provider: ProviderSummary;
  customer: { id: number; username: string; display_name: string };
  /**
   * Who did the job, frozen onto the booking. `null` for the shop itself.
   *
   * Not just a display name: a tip is attributed to this person, so the
   * endpoint needs the id.
   */
  staff: { id: number; name: string; photo: string | null } | null;
  status: BookingStatus;
  starts_at: string;
  ends_at: string;
  duration_minutes: number;
  subtotal: number;
  subtotal_display: string;
  platform_fee: number;
  platform_fee_display: string;
  total: number;
  total_display: string;
  currency: string;
  deposit: number;
  deposit_display: string;
  balance: number;
  balance_display: string;
  amount_paid: number;
  amount_due: number;
  requires_deposit: boolean;
  cancellation_window_hours: number;
  cancellation_deadline: string;
  is_late_cancellation: boolean;
  late_cancel_fee: number;
  late_cancel_fee_display: string;
  notes: string;
  items: BookingItem[];
  can_be_cancelled: boolean;
  is_paid: boolean;
  cancelled_at: string | null;
  cancellation_reason: string;
  created_at: string;
}

export interface Quote {
  currency: string;
  subtotal: number;
  subtotal_display: string;
  platform_fee: number;
  platform_fee_display: string;
  total: number;
  total_display: string;
  /**
   * What is taken now to secure the slot, and what is owed on arrival.
   * Both zero on a service with no deposit policy. Shown before checkout,
   * never applied after — a deposit the customer discovers at the payment
   * screen is a complaint.
   */
  deposit_percent: number;
  deposit: number;
  deposit_display: string;
  balance: number;
  balance_display: string;
  /**
   * The shop's cancellation policy, quoted before checkout. A customer who only
   * hears about a fee when they cancel it has been told too late to consent to
   * it, so it appears on the quote rather than only at cancellation.
   */
  cancellation_window_hours: number;
  late_cancel_fee_percent: number;
  late_cancel_fee: number;
  late_cancel_fee_display: string;
  duration_minutes: number;
  starts_at: string;
  ends_at: string;
  /**
   * What the code did, stated back.
   *
   * The server resolves and prices the code; the app never computes a
   * discount. It shows what came back so the customer can see the code was
   * understood rather than silently ignored.
   */
  promo_code: string | null;
  promo_description: string;
  points_spent: number;
  /** What those points were worth, in paise, as the server priced them. */
  points_worth_minor: number;
  items: { service_id: number; name: string; unit_price: number; unit_price_display: string; duration_minutes: number }[];
  is_available: boolean;
}

/**
 * What a customer has in their loyalty balance.
 *
 * `expiring_soon` is carried alongside the balance on purpose: a number that
 * quietly shrinks is a number nobody trusts, so the app says which points are
 * about to go rather than letting them discover it at checkout.
 */
export interface PointsBalance {
  available: number;
  expiring_soon: number;
  /** What the available points are worth, in paise, at the platform's rate. */
  worth_minor: number;
}

/** One movement in the points history. */
export interface PointsEntry {
  id: number;
  points: number;
  reason: string;
  shop: string | null;
  created_at: string;
  expires_at: string | null;
}

export interface Review {
  id: number;
  provider: number;
  provider_name: string;
  customer_display_name: string;
  customer_username: string;
  booking: number | null;
  rating: number;
  comment: string;
  provider_reply: string;
  replied_at: string | null;
  created_at: string;
}

export interface ReviewSummary {
  average: number | null;
  total: number;
}

export interface RescheduleRefused {
  rescheduled: false;
  reason?: 'price_changed';
  message: string;
  old_total?: number;
  new_total?: number;
  difference?: number;
  cancelled?: boolean;
  late_cancel_fee?: number;
  booking?: Booking;
}

export interface AvailabilitySlot {
  starts_at: string;
  ends_at: string;
  is_available: boolean;
  price: number | null;
}

export interface Availability {
  provider: number;
  slot_interval_minutes: number;
  opening_time: string;
  closing_time: string;
  slots: AvailabilitySlot[];
}

export interface Payment {
  id: number;
  booking: number;
  booking_reference: string;
  razorpay_order_id: string;
  razorpay_payment_id: string;
  amount: number;
  amount_display: string;
  currency: string;
  status: PaymentStatus;
  method: string;
  is_captured: boolean;
  captured_at: string | null;
  failure_reason: string;
  created_at: string;
}

/** DRF's paginated envelope, plus the extras some list endpoints add. */
export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface ProviderPage extends Paginated<ProviderListItem> {
  search_origin: Coordinates | null;
  radius_km: number;
}

export interface BookingPage extends Paginated<Booking> {
  role: Role;
}

export interface ReviewPage extends Paginated<Review> {
  summary: ReviewSummary;
}

export interface ServiceTypeOption {
  value: ServiceType;
  label: string;
}

export interface PushToken {
  id: string;
  token: string;
  platform: string;
  active: boolean;
  created_at: string;
  last_seen_at: string;
}

export interface LoginAudit {
  created_at: string;
  ip_address: string | null;
  succeeded: boolean;
  reason: string;
}