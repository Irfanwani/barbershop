/**
 * Types for the slice of the API the marketing site reads.
 *
 * Hand-written rather than generated. The site touches four endpoints, and a
 * generated client for four endpoints is a build step that has to be re-run
 * every time the API changes — including by someone who has not looked at the
 * website. These describe only what is actually used, so an unrelated field
 * changing shape cannot break the build.
 */

export interface PriceBand {
  service_type: string;
  service_type_label: string;
  median: number;
  median_display: string;
  minimum_display: string | null;
  maximum_display: string | null;
  p25_display: string;
  p75_display: string;
  sample_size: number;
  is_thin: boolean;
}

export interface ApproximateLocation {
  lat: number;
  lng: number;
}

export interface Provider {
  id: number;
  display_name: string;
  service_type: string;
  service_type_label: string;
  photo: string | null;
  rating_average: number | null;
  rating_count: number;
  is_open_now: boolean;
  is_accepting_bookings: boolean;
  starting_price_display: string | null;
  approximate_location: ApproximateLocation | null;
}

export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface Origin {
  lat: number;
  lng: number;
}