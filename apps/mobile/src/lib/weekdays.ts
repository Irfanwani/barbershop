/**
 * Weekly opening hours, as the app thinks about them.
 *
 * Separate from the screen so the numbering can be tested. `weekday` follows
 * Django's convention — 0 is Monday, 6 is Sunday — and getting that wrong by one
 * produces "closed on the wrong day", which looks like a server bug and is not.
 */

import type { WorkingHours } from '@/types/api';

export const WEEKDAY_NAMES = [
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
] as const;

export type DayDraft = {
  weekday: number;
  isClosed: boolean;
  opensAt: string;
  closesAt: string;
};

export const SUNDAY = 6;

export type DefaultHours = {
  opening_time: string;
  closing_time: string;
};

/**
 * A day the provider has never set: open, at the shop's default hours.
 *
 * Sunday is closed. A barber's shop that opens on Sunday is the exception, and
 * defaulting it open would put every provider on the platform on air for a day
 * most of them do not work.
 */
export function defaultDay(weekday: number, hours: DefaultHours): DayDraft {
  return {
    weekday,
    isClosed: weekday === SUNDAY,
    opensAt: hours.opening_time,
    closesAt: hours.closing_time,
  };
}

/**
 * The full week, with whatever the server already knows filled in.
 *
 * Days the server has no row for fall back to the default. Treating a missing
 * row as "shut" would silently close a provider who never touched the screen.
 */
export function buildWeek(
  saved: WorkingHours[] | undefined,
  hours: DefaultHours,
): DayDraft[] {
  return WEEKDAY_NAMES.map((_, weekday) => {
    const existing = saved?.find((day) => day.weekday === weekday);
    if (!existing) return defaultDay(weekday, hours);

    return {
      weekday,
      isClosed: existing.is_closed,
      opensAt: existing.opens_at,
      closesAt: existing.closes_at,
    };
  });
}

/** The shape the API expects. */
export function toApiDays(days: DayDraft[]) {
  return days.map((day) => ({
    weekday: day.weekday,
    is_closed: day.isClosed,
    opens_at: day.opensAt.trim(),
    closes_at: day.closesAt.trim(),
  }));
}

/**
 * The first thing wrong with a week, as a sentence a person can act on.
 *
 * Returns null when the week is fine. Checked here as well as on the server,
 * because a day that closes before it opens is nearly always a typo and
 * catching it inline beats a round trip.
 */
export function validateWeek(
  days: DayDraft[],
  defaultOpening: string,
  defaultClosing: string,
): string | null {
  // An empty week means the screen is still loading, not that the week is fine.
  if (!days.length) return 'Still loading your days.';

  if (defaultClosing.trim() <= defaultOpening.trim()) {
    return 'Closing time has to be after opening time.';
  }

  const bad = days.find((day) => !day.isClosed && day.closesAt.trim() <= day.opensAt.trim());
  if (bad) return `${WEEKDAY_NAMES[bad.weekday]} closes before it opens.`;

  return null;
}

/** How many days are actually open, for the summary line. */
export function openDayCount(days: DayDraft[]): number {
  return days.filter((day) => !day.isClosed).length;
}