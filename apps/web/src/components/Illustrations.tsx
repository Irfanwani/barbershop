import type { ComponentType } from 'react';

import type { FeatureArt, StepArt } from '@/content/site';

/**
 * The illustration set.
 *
 * Every picture is drawn for the thing beside it — a map for finding a shop, a
 * calendar for real availability, a split coin for deposits. The animation
 * classes (`art-draw`, `art-pop`, `art-rise`) are driven by the nearest
 * `.reveal.is-visible`, so a drawing comes to life when its card reaches the
 * viewport rather than all at once on page load.
 *
 * Colours come from `--art-*` custom properties set by the surrounding block,
 * which lets the same drawing sit on a cream card or a dark provider card.
 */

const stroke = {
  fill: 'none',
  stroke: 'var(--art-ink)',
  strokeWidth: 2.4,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const;

const thinStroke = { ...stroke, strokeWidth: 1.8 } as const;

function NearbyArt() {
  return (
    <svg className="feature-art" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <path
        d="M9 15.5 24 10l16 6 15-5.5v33L40 49l-16-6-15 6Z"
        fill="var(--art-bg)"
        stroke="var(--art-ink)"
        strokeWidth="2.2"
        strokeLinejoin="round"
      />
      <path d="M24 10v33M40 16v33" {...thinStroke} opacity=".3" />
      <path
        className="art-draw d1"
        pathLength={1}
        d="M15 41c5.5-1.5 6.5-9 11-12s7.5 7 12 4 4.5-8 9-10"
        stroke="var(--art-1)"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeDasharray="3.5 4.5"
        fill="none"
      />
      <g className="art-pop d2">
        <path
          d="M22 19c4.4 0 8 3.6 8 8 0 5.6-8 13-8 13s-8-7.4-8-13c0-4.4 3.6-8 8-8Z"
          fill="var(--art-1)"
        />
        <circle cx="22" cy="27" r="2.8" fill="var(--cream)" />
      </g>
      <g className="art-pop d3">
        <path
          d="M43 29c3.9 0 7 3.1 7 7 0 4.9-7 11.4-7 11.4S36 40.9 36 36c0-3.9 3.1-7 7-7Z"
          fill="var(--art-2)"
        />
        <circle cx="43" cy="36" r="2.5" fill="var(--art-ink)" />
      </g>
    </svg>
  );
}

function AvailabilityArt() {
  return (
    <svg className="feature-art" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <rect
        x="9"
        y="13"
        width="46"
        height="43"
        rx="10"
        fill="var(--art-bg)"
        stroke="var(--art-ink)"
        strokeWidth="2.2"
      />
      <path d="M9 26h46" {...stroke} />
      <path d="M21 8v11M43 8v11" stroke="var(--art-1)" strokeWidth="3.2" strokeLinecap="round" />
      <g fill="var(--art-ink)" opacity=".22">
        <circle cx="20" cy="35" r="2" />
        <circle cx="30" cy="35" r="2" />
        <circle cx="40" cy="35" r="2" />
        <circle cx="20" cy="44" r="2" />
        <circle cx="30" cy="44" r="2" />
      </g>
      <rect
        className="art-pop d2"
        x="37"
        y="39"
        width="15"
        height="12"
        rx="4"
        fill="var(--art-1)"
      />
      <path
        className="art-draw d3"
        pathLength={1}
        d="m41 45 2.8 3 5.2-6"
        stroke="var(--cream)"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}

function PriceArt() {
  return (
    <svg className="feature-art" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <path
        d="M18 8h28v49l-4.7-3.6L36.7 57l-4.7-3.6L27.3 57l-4.6-3.6L18 57Z"
        fill="var(--art-bg)"
        stroke="var(--art-ink)"
        strokeWidth="2.2"
        strokeLinejoin="round"
      />
      <path d="M25 19h14M25 26h9" {...stroke} opacity=".55" />
      <rect
        className="art-pop d2"
        x="24"
        y="33"
        width="16"
        height="13"
        rx="4"
        fill="var(--art-1)"
      />
      <path
        d="M31 37v6M29 38.5h4M29 41h4l-4 2.5"
        stroke="var(--cream)"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <path
        className="art-draw d3"
        pathLength={1}
        d="M27 52h10"
        stroke="var(--art-ink)"
        strokeWidth="2.2"
        strokeLinecap="round"
        opacity=".35"
      />
    </svg>
  );
}

function DepositArt() {
  return (
    <svg className="feature-art" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <rect
        x="7"
        y="25"
        width="50"
        height="29"
        rx="8"
        fill="var(--art-bg)"
        stroke="var(--art-ink)"
        strokeWidth="2.2"
      />
      <path d="M7 33h50" {...thinStroke} opacity=".4" />
      <rect
        x="14"
        y="13"
        width="34"
        height="21"
        rx="5"
        fill="var(--art-2)"
        stroke="var(--art-ink)"
        strokeWidth="2.2"
      />
      <path d="M14 20h34" {...thinStroke} opacity=".55" />
      <path d="M19 28h8" stroke="var(--art-ink)" strokeWidth="2" strokeLinecap="round" opacity=".55" />
      <circle
        className="art-pop d2"
        cx="46"
        cy="41"
        r="10"
        fill="var(--art-1)"
        stroke="var(--art-ink)"
        strokeWidth="1.8"
      />
      <path
        d="M44 36.5v9M41.8 39h4.4M41.8 41.5h4.4L42 45"
        stroke="var(--cream)"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}

function ReminderArt() {
  return (
    <svg className="feature-art" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <path
        className="art-draw d1"
        pathLength={1}
        d="M32 10c-8.5 0-13.5 6.6-13.5 15.5v8.7L13 42h38l-5.5-7.8v-8.7C45.5 16.6 40.5 10 32 10Z"
        fill="var(--art-bg)"
        stroke="var(--art-ink)"
        strokeWidth="2.2"
        strokeLinejoin="round"
      />
      <path
        d="M26.5 48a5.5 5.5 0 0 0 11 0"
        stroke="var(--art-ink)"
        strokeWidth="2.4"
        strokeLinecap="round"
        fill="none"
      />
      <circle
        className="art-pop d2"
        cx="49"
        cy="14"
        r="9"
        fill="var(--art-1)"
        stroke="var(--cream)"
        strokeWidth="2"
      />
      <path
        d="M49 10v4.2l2.4 1.8"
        stroke="var(--cream)"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <path
        className="art-rise d3"
        d="M18 17.5 14.5 14M46 18l3.5-4"
        stroke="var(--art-2)"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
    </svg>
  );
}

function ProductsArt() {
  return (
    <svg className="feature-art" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <rect
        x="12"
        y="23"
        width="18"
        height="33"
        rx="6"
        fill="var(--art-bg)"
        stroke="var(--art-ink)"
        strokeWidth="2.2"
      />
      <rect x="17" y="13" width="8" height="10" rx="2" fill="var(--art-1)" />
      <path d="M17 33h8M17 38h8" {...thinStroke} opacity=".4" />
      <g className="art-pop d2">
        <rect
          x="37"
          y="17"
          width="15"
          height="36"
          rx="4"
          fill="var(--art-2)"
          stroke="var(--art-ink)"
          strokeWidth="2.2"
        />
        <path
          d="M41.5 17v36M45 17v36M48.5 17v36"
          stroke="var(--art-ink)"
          strokeWidth="1.2"
          opacity=".45"
        />
      </g>
      <circle
        className="art-pop d3"
        cx="48"
        cy="47"
        r="9"
        fill="var(--art-1)"
        stroke="var(--cream)"
        strokeWidth="2"
      />
      <path
        d="M44.5 47h7M48 43.5v7"
        stroke="var(--cream)"
        strokeWidth="1.7"
        strokeLinecap="round"
      />
    </svg>
  );
}

function HoursArt() {
  return (
    <svg className="feature-art" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <circle
        cx="32"
        cy="33"
        r="22"
        fill="var(--art-bg)"
        stroke="var(--art-ink)"
        strokeWidth="2.2"
      />
      <path
        d="M32 6v4M32 56v4M5 33h4M55 33h4"
        stroke="var(--art-2)"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
      <path
        className="art-draw d1"
        pathLength={1}
        d="M32 19v14l9 5.5"
        stroke="var(--art-1)"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <circle cx="32" cy="33" r="2.6" fill="var(--art-ink)" />
      <circle
        className="art-pop d2"
        cx="50"
        cy="15"
        r="8"
        fill="var(--art-2)"
        stroke="var(--cream)"
        strokeWidth="2"
      />
      <path
        d="M50 11.5v3.7l2 1.5"
        stroke="var(--art-ink)"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}

function LedgerArt() {
  return (
    <svg className="feature-art" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <rect
        x="13"
        y="9"
        width="38"
        height="46"
        rx="7"
        fill="var(--art-bg)"
        stroke="var(--art-ink)"
        strokeWidth="2.2"
      />
      <rect x="24" y="5" width="16" height="9" rx="3" fill="var(--art-1)" />
      <path d="M21 24h22M21 31h15" {...thinStroke} opacity=".5" />
      <circle
        className="art-pop d2"
        cx="25"
        cy="44"
        r="7.5"
        fill="var(--art-2)"
        stroke="var(--art-ink)"
        strokeWidth="1.6"
      />
      <circle
        className="art-pop d3"
        cx="40"
        cy="44"
        r="7.5"
        fill="var(--art-1)"
        stroke="var(--art-ink)"
        strokeWidth="1.6"
      />
      <path
        d="M22 44h6M37 44h6"
        stroke="var(--cream)"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

function RefundArt() {
  return (
    <svg className="feature-art" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <path
        className="art-draw d1"
        pathLength={1}
        d="M51 35a19 19 0 1 1-5.6-15.5"
        stroke="var(--art-1)"
        strokeWidth="3"
        strokeLinecap="round"
        fill="none"
      />
      <path
        d="m45 10 .8 9.4-9.3-.8"
        stroke="var(--art-1)"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <circle
        cx="32"
        cy="36"
        r="11"
        fill="var(--art-bg)"
        stroke="var(--art-ink)"
        strokeWidth="2.2"
      />
      <path
        className="art-draw d3"
        pathLength={1}
        d="m27 36 3.5 3.5L37 32"
        stroke="var(--art-ink)"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <circle className="art-pop d2" cx="48" cy="49" r="5" fill="var(--art-2)" />
    </svg>
  );
}

function EarningsArt() {
  return (
    <svg className="feature-art" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <path d="M10 52h44" {...thinStroke} opacity=".4" />
      <rect x="15" y="37" width="9" height="15" rx="2.5" fill="var(--art-2)" />
      <rect x="28" y="29" width="9" height="23" rx="2.5" fill="var(--art-1)" />
      <rect x="41" y="20" width="9" height="32" rx="2.5" fill="var(--art-ink)" opacity=".75" />
      <path
        className="art-draw d1"
        pathLength={1}
        d="m13 30 11-8 8 4 17-13"
        stroke="var(--art-1)"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <path
        d="M43 13h6v6"
        stroke="var(--art-1)"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
        className="art-pop d2"
      />
      <circle
        className="art-pop d3"
        cx="52"
        cy="48"
        r="7"
        fill="var(--art-2)"
        stroke="var(--cream)"
        strokeWidth="2"
      />
      <path
        d="M52 44.5v7M49.8 46.5h4.4M49.8 48.8h4.4"
        stroke="var(--art-ink)"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  );
}

function TeamArt() {
  return (
    <svg className="feature-art" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <circle cx="23" cy="23" r="8.5" fill="var(--art-2)" stroke="var(--art-ink)" strokeWidth="2" />
      <path
        d="M9 51c0-8.5 6-14 14-14s14 5.5 14 14"
        fill="var(--art-bg)"
        stroke="var(--art-ink)"
        strokeWidth="2.2"
        strokeLinejoin="round"
      />
      <circle
        className="art-pop d2"
        cx="45"
        cy="20"
        r="7.5"
        fill="var(--art-1)"
        stroke="var(--art-ink)"
        strokeWidth="2"
      />
      <path
        className="art-rise d3"
        d="M34 45c0-7 5-11.5 11-11.5S56 38 56 45"
        fill="var(--art-bg)"
        stroke="var(--art-ink)"
        strokeWidth="2.2"
        strokeLinejoin="round"
      />
      <path
        d="M39 52h13"
        stroke="var(--art-1)"
        strokeWidth="2.2"
        strokeLinecap="round"
        opacity=".7"
      />
    </svg>
  );
}

function OrdersArt() {
  return (
    <svg className="feature-art" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <path
        d="m9 23 23-10 23 10v28L32 61 9 51Z"
        fill="var(--art-bg)"
        stroke="var(--art-ink)"
        strokeWidth="2.2"
        strokeLinejoin="round"
      />
      <path d="m9 23 23 10 23-10M32 33v28" {...thinStroke} opacity=".55" />
      <rect x="22" y="16" width="20" height="7" rx="2.5" fill="var(--art-2)" />
      <circle
        className="art-pop d2"
        cx="46"
        cy="46"
        r="9"
        fill="var(--art-1)"
        stroke="var(--cream)"
        strokeWidth="2"
      />
      <path
        className="art-draw d3"
        pathLength={1}
        d="m42 46 3 3 5.5-6"
        stroke="var(--cream)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}

const FEATURE_ART: Record<FeatureArt, ComponentType> = {
  nearby: NearbyArt,
  availability: AvailabilityArt,
  price: PriceArt,
  deposit: DepositArt,
  reminder: ReminderArt,
  products: ProductsArt,
  hours: HoursArt,
  ledger: LedgerArt,
  refund: RefundArt,
  earnings: EarningsArt,
  team: TeamArt,
  orders: OrdersArt,
};

export function FeatureArtwork({ art }: { art: FeatureArt }) {
  const Art = FEATURE_ART[art];
  return <Art />;
}

/* --- the three booking steps --------------------------------------------- */

function DownloadStepArt() {
  return (
    <svg className="step-art" viewBox="0 0 220 160" aria-hidden="true" focusable="false">
      <circle cx="110" cy="80" r="62" fill="var(--art-bg)" />
      <circle
        className="art-draw d1"
        pathLength={1}
        cx="110"
        cy="80"
        r="72"
        fill="none"
        stroke="var(--art-2)"
        strokeWidth="1.5"
        strokeDasharray="4 7"
      />
      <rect
        x="74"
        y="16"
        width="72"
        height="128"
        rx="17"
        fill="var(--card)"
        stroke="var(--art-ink)"
        strokeWidth="2.8"
      />
      <rect x="88" y="34" width="44" height="44" rx="12" fill="var(--art-1)" />
      <circle cx="103" cy="50" r="5" fill="none" stroke="var(--cream)" strokeWidth="2.2" />
      <circle cx="103" cy="62" r="5" fill="none" stroke="var(--cream)" strokeWidth="2.2" />
      <path
        d="m107 54 15-8M107 58l15 8"
        stroke="var(--cream)"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
      <path
        className="art-draw d2"
        pathLength={1}
        d="M110 91v23M100 106l10 10 10-10"
        stroke="var(--art-1)"
        strokeWidth="3.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <rect x="92" y="125" width="36" height="4" rx="2" fill="var(--art-ink)" opacity=".25" />
      <g className="art-pop d3">
        <path
          d="m46 39 3.5 8.5L58 51l-8.5 3.5L46 63l-3.5-8.5L34 51l8.5-3.5Z"
          fill="var(--art-2)"
        />
        <circle cx="172" cy="112" r="6" fill="var(--art-1)" />
        <circle cx="163" cy="35" r="4" fill="var(--art-ink)" opacity=".35" />
      </g>
      <path
        className="art-rise d3"
        d="M37 111h13M43.5 104.5v13M171 68h12"
        stroke="var(--art-ink)"
        strokeWidth="2.2"
        strokeLinecap="round"
        opacity=".4"
      />
    </svg>
  );
}

function FindStepArt() {
  return (
    <svg className="step-art" viewBox="0 0 220 160" aria-hidden="true" focusable="false">
      <rect
        x="22"
        y="22"
        width="176"
        height="118"
        rx="22"
        fill="var(--art-bg)"
        stroke="var(--art-ink)"
        strokeWidth="2.4"
      />
      <path
        d="M22 58h176M22 96h176M76 22v118M148 22v118"
        stroke="var(--art-ink)"
        strokeWidth="1.2"
        opacity=".16"
      />
      <path
        className="art-draw d1"
        pathLength={1}
        d="M47 116c18-6 20-32 37-38s20 21 35 14 14-30 30-32 17 10 28 7"
        stroke="var(--art-1)"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeDasharray="4 5"
        fill="none"
      />
      <g className="art-pop d2">
        <path
          d="M76 52c7 0 12.5 5.6 12.5 12.5C88.5 74 76 88 76 88s-12.5-14-12.5-23.5C63.5 57.6 69 52 76 52Z"
          fill="var(--art-1)"
        />
        <circle cx="76" cy="65" r="4.2" fill="var(--cream)" />
      </g>
      <g className="art-pop d3">
        <path
          d="M153 71c5.8 0 10.5 4.7 10.5 10.5C163.5 89 153 101 153 101s-10.5-12-10.5-19.5c0-5.8 4.7-10.5 10.5-10.5Z"
          fill="var(--art-2)"
        />
        <circle cx="153" cy="82" r="3.6" fill="var(--art-ink)" />
      </g>
      <g className="art-pop d3">
        <circle cx="142" cy="54" r="22" fill="var(--cream)" stroke="var(--art-ink)" strokeWidth="3" />
        <path
          d="m157 70 15 15"
          stroke="var(--art-ink)"
          strokeWidth="6"
          strokeLinecap="round"
        />
        <circle cx="142" cy="54" r="12" fill="none" stroke="var(--art-1)" strokeWidth="2.4" />
      </g>
      <path
        className="art-rise d3"
        d="m36 37 4-9 4 9 9 4-9 4-4 9-4-9-9-4Z"
        fill="var(--art-2)"
        opacity=".9"
      />
    </svg>
  );
}

function BookStepArt() {
  return (
    <svg className="step-art" viewBox="0 0 220 160" aria-hidden="true" focusable="false">
      <rect
        x="28"
        y="22"
        width="148"
        height="120"
        rx="22"
        fill="var(--art-bg)"
        stroke="var(--art-ink)"
        strokeWidth="2.4"
      />
      <path d="M28 56h148" stroke="var(--art-ink)" strokeWidth="2.2" />
      <path
        d="M70 12v21M134 12v21"
        stroke="var(--art-1)"
        strokeWidth="5"
        strokeLinecap="round"
      />
      <g fill="var(--art-ink)" opacity=".2">
        <circle cx="55" cy="77" r="3" />
        <circle cx="79" cy="77" r="3" />
        <circle cx="103" cy="77" r="3" />
        <circle cx="127" cy="77" r="3" />
        <circle cx="55" cy="101" r="3" />
        <circle cx="79" cy="101" r="3" />
      </g>
      <rect
        className="art-pop d2"
        x="96"
        y="68"
        width="54"
        height="42"
        rx="10"
        fill="var(--art-1)"
      />
      <path
        className="art-draw d3"
        pathLength={1}
        d="m111 89 8 8 18-19"
        stroke="var(--cream)"
        strokeWidth="4"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <circle
        className="art-pop d3"
        cx="178"
        cy="118"
        r="19"
        fill="var(--art-2)"
        stroke="var(--art-ink)"
        strokeWidth="2.2"
      />
      <path
        d="M178 108v10l7 4"
        stroke="var(--art-ink)"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <path
        className="art-rise d3"
        d="m45 28 3.5 7.5L56 39l-7.5 3.5L45 50l-3.5-7.5L34 39l7.5-3.5Z"
        fill="var(--art-2)"
      />
    </svg>
  );
}

const STEP_ART: Record<StepArt, ComponentType> = {
  download: DownloadStepArt,
  find: FindStepArt,
  book: BookStepArt,
};

export function StepArtwork({ art }: { art: StepArt }) {
  const Art = STEP_ART[art];
  return <Art />;
}

/* --- knowledge base icons ------------------------------------------------ */

export function GroupArtwork({ id }: { id: string }) {
  switch (id) {
    case 'booking':
      return (
        <svg className="group-art" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
          <rect x="4" y="7" width="24" height="21" rx="6" fill="currentColor" opacity=".14" />
          <path d="M4 13h24M10 4v6M22 4v6" {...thinStroke} />
          <path d="m11 20 3 3 6-7" {...thinStroke} />
        </svg>
      );
    case 'changes':
      return (
        <svg className="group-art" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
          <path
            d="M25 13a9.5 9.5 0 1 0 .5 6"
            {...thinStroke}
            strokeWidth="2.2"
          />
          <path d="m20 7 5 .5.5 5" {...thinStroke} strokeWidth="2.2" />
          <path d="M9 19h9M9 23h6" {...thinStroke} opacity=".5" />
        </svg>
      );
    case 'shop':
      return (
        <svg className="group-art" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
          <path d="M6 11h20l-1.5 15h-17Z" {...thinStroke} strokeWidth="2.2" />
          <path d="M11 11V9a5 5 0 0 1 10 0v2" {...thinStroke} strokeWidth="2.2" />
          <path d="M12 17h8" {...thinStroke} opacity=".5" />
        </svg>
      );
    case 'provider':
      return (
        <svg className="group-art" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
          <path d="M6 12h20v13H6Z" fill="currentColor" opacity=".14" />
          <path d="M4 12h24M7 12l1.5 13h15L25 12M11 12V8h10v4" {...thinStroke} strokeWidth="2.2" />
          <path d="M13 19h6" {...thinStroke} opacity=".5" />
        </svg>
      );
    case 'account':
      return (
        <svg className="group-art" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
          <circle cx="16" cy="11" r="5" fill="currentColor" opacity=".16" />
          <circle cx="16" cy="11" r="5" {...thinStroke} strokeWidth="2.2" />
          <path d="M6 27c0-6 4.5-10 10-10s10 4 10 10" {...thinStroke} strokeWidth="2.2" />
        </svg>
      );
    default:
      return (
        <svg className="group-art" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
          <circle cx="16" cy="16" r="11" {...thinStroke} strokeWidth="2.2" />
          <path d="M16 15v7M16 10.5v.5" {...thinStroke} strokeWidth="2.2" />
        </svg>
      );
  }
}

/* --- larger scenes ------------------------------------------------------- */

export function KnowledgeHeroArt() {
  return (
    <svg className="kb-hero-art" viewBox="0 0 360 300" aria-hidden="true" focusable="false">
      <circle cx="192" cy="146" r="118" fill="var(--art-bg)" />
      <circle
        className="art-draw d1"
        pathLength={1}
        cx="192"
        cy="146"
        r="136"
        fill="none"
        stroke="var(--art-2)"
        strokeWidth="1.6"
        strokeDasharray="3 9"
      />
      <path
        className="art-draw d1"
        pathLength={1}
        d="M151 112c0-31 58-43 78-10 18 30-25 42-38 54-8 8-7 18-7 27"
        stroke="var(--art-1)"
        strokeWidth="16"
        strokeLinecap="round"
        fill="none"
      />
      <circle className="art-pop d2" cx="184" cy="219" r="9" fill="var(--art-1)" />
      <g className="art-pop d2">
        <rect x="238" y="62" width="78" height="52" rx="16" fill="var(--card)" stroke="var(--art-ink)" strokeWidth="2.4" />
        <path d="M258 84h38M258 94h26" stroke="var(--art-ink)" strokeWidth="2.2" strokeLinecap="round" opacity=".45" />
        <path d="m252 114-5 13 16-8" fill="var(--card)" stroke="var(--art-ink)" strokeWidth="2.4" strokeLinejoin="round" />
      </g>
      <g className="art-pop d3">
        <rect x="42" y="174" width="84" height="64" rx="16" fill="var(--card)" stroke="var(--art-ink)" strokeWidth="2.4" />
        <path d="M42 194h84" stroke="var(--art-ink)" strokeWidth="2" />
        <path d="M62 166v14M104 166v14" stroke="var(--art-1)" strokeWidth="4" strokeLinecap="round" />
        <circle cx="64" cy="210" r="4" fill="var(--art-2)" />
        <circle cx="80" cy="210" r="4" fill="var(--art-1)" />
        <circle cx="96" cy="210" r="4" fill="var(--art-ink)" opacity=".25" />
      </g>
      <g className="art-pop d3">
        <circle cx="293" cy="185" r="31" fill="var(--art-2)" />
        <circle cx="283" cy="176" r="5" fill="none" stroke="var(--art-ink)" strokeWidth="2.4" />
        <circle cx="283" cy="192" r="5" fill="none" stroke="var(--art-ink)" strokeWidth="2.4" />
        <path d="m287 180 12-7M287 188l12 7" stroke="var(--art-ink)" strokeWidth="2.4" strokeLinecap="round" />
      </g>
      <path className="art-rise d3" d="m106 84 6-13 6 13 13 6-13 6-6 13-6-13-13-6Z" fill="var(--art-2)" />
      <path className="art-rise d3" d="m306 35 3.5 8 8 3.5-8 3.5-3.5 8-3.5-8-8-3.5 8-3.5Z" fill="var(--art-1)" />
    </svg>
  );
}

export function DownloadArt() {
  return (
    <svg className="download-art" viewBox="0 0 320 280" aria-hidden="true" focusable="false">
      <circle cx="168" cy="140" r="112" fill="var(--art-bg)" opacity=".55" />
      <circle
        className="art-draw d1"
        pathLength={1}
        cx="168"
        cy="140"
        r="132"
        fill="none"
        stroke="var(--cream)"
        strokeWidth="1.4"
        strokeDasharray="3 8"
        opacity=".5"
      />
      <rect
        x="115"
        y="33"
        width="106"
        height="206"
        rx="26"
        fill="var(--card)"
        stroke="var(--art-ink)"
        strokeWidth="3"
      />
      <rect x="133" y="61" width="70" height="64" rx="16" fill="var(--art-1)" />
      <circle cx="156" cy="87" r="7" fill="none" stroke="var(--cream)" strokeWidth="2.8" />
      <circle cx="156" cy="105" r="7" fill="none" stroke="var(--cream)" strokeWidth="2.8" />
      <path d="m162 94 21-11M162 100l21 11" stroke="var(--cream)" strokeWidth="2.8" strokeLinecap="round" />
      <path
        className="art-draw d2"
        pathLength={1}
        d="M168 144v34M152 164l16 15 16-15"
        stroke="var(--art-1)"
        strokeWidth="4.2"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <rect x="140" y="207" width="56" height="6" rx="3" fill="var(--art-ink)" opacity=".2" />
      <g className="art-pop d3">
        <path d="m57 64 7-15 7 15 15 7-15 7-7 15-7-15-15-7Z" fill="var(--art-2)" />
        <path d="m252 162 5-11 5 11 11 5-11 5-5 11-5-11-11-5Z" fill="var(--art-2)" />
        <circle cx="266" cy="78" r="7" fill="var(--art-3)" />
        <circle cx="47" cy="181" r="5" fill="var(--cream)" opacity=".8" />
      </g>
      <path
        className="art-rise d3"
        d="M72 113h18M81 104v18M246 220h14M253 213v14"
        stroke="var(--cream)"
        strokeWidth="2.4"
        strokeLinecap="round"
        opacity=".7"
      />
    </svg>
  );
}

/* --- small marks used around the site ----------------------------------- */

export function Sparkle({ className = '' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path
        d="m12 2 2.3 7.7L22 12l-7.7 2.3L12 22l-2.3-7.7L2 12l7.7-2.3Z"
        fill="currentColor"
      />
    </svg>
  );
}

export function StarIcon({ className = '' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 20 20" aria-hidden="true" focusable="false">
      <path
        d="m10 1.8 2.5 5.1 5.6.8-4 3.9.9 5.6-5-2.6-5 2.6.9-5.6-4-3.9 5.6-.8Z"
        fill="currentColor"
      />
    </svg>
  );
}

export function PinIcon({ className = '' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 20 20" aria-hidden="true" focusable="false">
      <path
        d="M10 1.8c3.5 0 6.3 2.8 6.3 6.3 0 4.6-6.3 10.1-6.3 10.1S3.7 12.7 3.7 8.1C3.7 4.6 6.5 1.8 10 1.8Z"
        fill="currentColor"
      />
      <circle cx="10" cy="8" r="2.2" fill="var(--cream)" />
    </svg>
  );
}

export function CheckIcon({ className = '' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 20 20" aria-hidden="true" focusable="false">
      <path
        d="m4.5 10.5 3.4 3.4 7.6-8"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function ArrowUpRight({ className = '' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 20 20" aria-hidden="true" focusable="false">
      <path
        d="M6 14 14 6M7.5 6H14v6.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function ScissorsMark({ className = '' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 32 28" aria-hidden="true" focusable="false">
      <circle cx="7" cy="7" r="3.4" fill="none" stroke="currentColor" strokeWidth="2" />
      <circle cx="7" cy="21" r="3.4" fill="none" stroke="currentColor" strokeWidth="2" />
      <path
        d="m10 9 16 11M10 19 26 8"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
    </svg>
  );
}


