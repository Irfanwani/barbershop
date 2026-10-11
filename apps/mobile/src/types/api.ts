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
  is_accepting_bookings: boolean;
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
  duration_minutes: number;
  starts_at: string;
  ends_at: string;
  items: { service_id: number; name: string; unit_price: number; unit_price_display: string; duration_minutes: number }[];
  is_available: boolean;
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