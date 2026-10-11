/**
 * Weekly opening hours.
 *
 * The weekday numbering is the thing worth pinning. It follows Django — 0 is
 * Monday — and an off-by-one here does not throw, it just quietly closes every
 * shop on the wrong day.
 */

import {
  buildWeek,
  defaultDay,
  openDayCount,
  SUNDAY,
  toApiDays,
  validateWeek,
  WEEKDAY_NAMES,
} from '@/lib/weekdays';
import type { WorkingHours } from '@/types/api';

const HOURS = { opening_time: '09:00', closing_time: '20:00' };

function saved(overrides: Partial<WorkingHours>): WorkingHours {
  return {
    id: 1,
    weekday: 0,
    weekday_label: 'Monday',
    is_closed: false,
    opens_at: '09:00',
    closes_at: '20:00',
    ...overrides,
  };
}

describe('weekday numbering', () => {
  it('starts the week on Monday', () => {
    // The API numbers weekdays from 0 on Monday. Sunday as 0 would shift every
    // day by one and read as a server bug rather than a client one.
    expect(WEEKDAY_NAMES[0]).toBe('Monday');
    expect(WEEKDAY_NAMES[6]).toBe('Sunday');
    expect(WEEKDAY_NAMES).toHaveLength(7);
  });

  it('has no gaps or repeats', () => {
    expect(new Set(WEEKDAY_NAMES).size).toBe(7);
  });
});

describe('defaultDay', () => {
  it('starts open at the shop\'s own hours', () => {
    const day = defaultDay(0, HOURS);

    expect(day.isClosed).toBe(false);
    expect(day.opensAt).toBe('09:00');
    expect(day.closesAt).toBe('20:00');
  });

  it('starts Sunday closed', () => {
    // A barber's shop that opens on Sunday is the exception. Defaulting it open
    // puts every provider on the platform on air for a day most do not work.
    expect(defaultDay(SUNDAY, HOURS).isClosed).toBe(true);
  });

  it('follows the shop\'s hours rather than a fixed default', () => {
    const day = defaultDay(2, { opening_time: '11:00', closing_time: '22:00' });

    expect(day.opensAt).toBe('11:00');
    expect(day.closesAt).toBe('22:00');
  });
});

describe('buildWeek', () => {
  it('returns seven days in order', () => {
    const week = buildWeek([], HOURS);

    expect(week).toHaveLength(7);
    expect(week.map((day) => day.weekday)).toEqual([0, 1, 2, 3, 4, 5, 6]);
  });

  it('fills in days the server has never heard of', () => {
    // A missing row means "not set", not "shut". Treating it as shut would
    // silently close a provider who has never opened the screen.
    const week = buildWeek(undefined, HOURS);

    expect(openDayCount(week)).toBe(6);
  });

  it('uses what the server already knows', () => {
    const week = buildWeek([saved({ weekday: 3, opens_at: '10:00', closes_at: '16:00' })], HOURS);

    expect(week[3]).toMatchObject({ isClosed: false, opensAt: '10:00', closesAt: '16:00' });
  });

  it('honours a day the server has closed', () => {
    const week = buildWeek([saved({ weekday: 2, is_closed: true })], HOURS);

    expect(week[2]?.isClosed).toBe(true);
  });

  it('does not let one saved day shift the others', () => {
    const week = buildWeek([saved({ weekday: 0, opens_at: '06:00', closes_at: '07:00' })], HOURS);

    expect(week[1]).toMatchObject({ opensAt: '09:00', closesAt: '20:00' });
  });

  it('does not let Sunday\'s default close Monday', () => {
    const week = buildWeek([], HOURS);

    for (const day of week.slice(0, 6)) {
      expect(day.isClosed).toBe(false);
    }
    expect(week[6]?.isClosed).toBe(true);
  });
});

describe('toApiDays', () => {
  it('maps to the field names the server expects', () => {
    const api = toApiDays([{ weekday: 1, isClosed: true, opensAt: ' 09:00 ', closesAt: ' 18:00 ' }]);

    expect(api).toEqual([
      { weekday: 1, is_closed: true, opens_at: '09:00', closes_at: '18:00' },
    ]);
  });

  it('sends every day, closed ones included', () => {
    // Omitting closed days would leave whatever the server had before, so a day
    // the provider switched off would stay on.
    expect(toApiDays(buildWeek([], HOURS))).toHaveLength(7);
  });
});

describe('validateWeek', () => {
  const week = buildWeek([], HOURS);

  it('accepts a sane week', () => {
    expect(validateWeek(week, '09:00', '20:00')).toBeNull();
  });

  it('names the day that closes before it opens', () => {
    const broken = week.map((day) =>
      day.weekday === 3 ? { ...day, opensAt: '18:00', closesAt: '09:00' } : day,
    );

    // A message naming the day beats "invalid input".
    expect(validateWeek(broken, '09:00', '20:00')).toBe('Thursday closes before it opens.');
  });

  it('ignores a closed day with nonsense times', () => {
    const broken = week.map((day) =>
      day.weekday === 6 ? { ...day, opensAt: '18:00', closesAt: '09:00' } : day,
    );

    // Sunday is shut; its leftover times are never used.
    expect(validateWeek(broken, '09:00', '20:00')).toBeNull();
  });

  it('catches equal opening and closing times', () => {
    const broken = week.map((day) => ({ ...day, opensAt: '09:00', closesAt: '09:00' }));

    expect(validateWeek(broken, '09:00', '20:00')).toMatch(/closes before it opens/);
  });

  it('checks the default hours too', () => {
    expect(validateWeek(week, '20:00', '09:00')).toBe(
      'Closing time has to be after opening time.',
    );
  });

  it('says so when the week has not loaded', () => {
    expect(validateWeek([], '09:00', '20:00')).toBe('Still loading your days.');
  });

  it('tolerates whitespace around the times', () => {
    expect(validateWeek(week, ' 09:00 ', ' 20:00 ')).toBeNull();
  });
});

describe('openDayCount', () => {
  it('counts only the days that are actually open', () => {
    expect(openDayCount(buildWeek([], HOURS))).toBe(6);
    expect(openDayCount([])).toBe(0);
  });
});