import { useState } from 'react';
import { Pressable, ScrollView, Text, TextInput, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

import { useColors } from '@/components/ui';
import { cn } from '@/lib/cn';
import type { ServiceTypeOption } from '@/types/api';

export type Filters = {
  serviceType: ServiceTypeOption['value'] | 'all';
  services: string[];
  openNow: boolean;
  minRating: number;
};

const COMMON_SERVICES = [
  'Haircut',
  'Beard trim',
  'Shave',
  'Hair wash',
  'Colour',
  'Facial',
  'Waxing',
  'Massage',
];

const RATINGS = [0, 3, 4, 4.5];

/**
 * The browse screen's filter row.
 *
 * Collapsed by default. A bar of chips across the top of a list costs a customer
 * about a fifth of the screen before they have seen a single shop, so the
 * filters live behind a button until they are wanted.
 */
export function SearchFilters({
  value,
  onChange,
  serviceTypes,
}: {
  value: Filters;
  onChange: (next: Filters) => void;
  serviceTypes: ServiceTypeOption[];
}) {
  const colors = useColors();
  const [open, setOpen] = useState(false);

  const activeCount =
    (value.serviceType !== 'all' ? 1 : 0) +
    value.services.length +
    (value.openNow ? 1 : 0) +
    (value.minRating ? 1 : 0);

  return (
    <View className="gap-3">
      <View className="flex-row items-center gap-2">
        <SearchField
          onSubmit={() => undefined}
          placeholder="Search shops and services"
          onChangeText={() => undefined}
          testID="provider-search"
        />
        <Pressable
          onPress={() => setOpen((current) => !current)}
          accessibilityRole="button"
          accessibilityLabel={open ? 'Hide filters' : 'Show filters'}
          testID="filters-toggle"
          className="h-12 w-12 items-center justify-center rounded-2xl border"
          style={{
            backgroundColor: activeCount > 0 ? colors.accent : colors.surface,
            borderColor: activeCount > 0 ? colors.accent : colors.border,
          }}>
          <Ionicons
            name="options-outline"
            size={18}
            color={activeCount > 0 ? colors.accentText : colors.text}
          />
          {activeCount > 0 ? (
            <View
              className="absolute -right-1 -top-1 h-5 w-5 items-center justify-center rounded-full"
              style={{ backgroundColor: colors.accentText }}>
              <Text className="text-2xs font-bold" style={{ color: colors.accent }}>
                {activeCount}
              </Text>
            </View>
          ) : null}
        </Pressable>
      </View>

      {open ? (
        <View className="gap-4 rounded-2xl border p-4" style={{ backgroundColor: colors.surface, borderColor: colors.border }}>
          <FilterGroup label="Category">
            <Chip
              label="All"
              selected={value.serviceType === 'all'}
              onPress={() => onChange({ ...value, serviceType: 'all' })}
            />
            {serviceTypes.map((type) => (
              <Chip
                key={type.value}
                label={type.label}
                selected={value.serviceType === type.value}
                onPress={() =>
                  onChange({ ...value, serviceType: value.serviceType === type.value ? 'all' : type.value })
                }
              />
            ))}
          </FilterGroup>

          <FilterGroup label="Must offer">
            <View className="flex-row flex-wrap gap-2">
              {COMMON_SERVICES.map((service) => {
                const selected = value.services.includes(service);
                return (
                  <Chip
                    key={service}
                    label={service}
                    selected={selected}
                    onPress={() =>
                      onChange({
                        ...value,
                        services: selected
                          ? value.services.filter((item) => item !== service)
                          : [...value.services, service],
                      })
                    }
                  />
                );
              })}
            </View>
          </FilterGroup>

          <FilterGroup label="Rating">
            <View className="flex-row flex-wrap gap-2">
              {RATINGS.map((rating) => (
                <Chip
                  key={rating}
                  label={rating === 0 ? 'Any' : `${rating}+`}
                  selected={value.minRating === rating}
                  onPress={() => onChange({ ...value, minRating: rating })}
                />
              ))}
            </View>
          </FilterGroup>

          <Pressable
            onPress={() => onChange({ serviceType: 'all', services: [], openNow: false, minRating: 0 })}
            accessibilityRole="button"
            className="self-start">
            <Text className="text-sm font-semibold" style={{ color: colors.accent }}>
              Clear all
            </Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );
}

function FilterGroup({ label, children }: { label: string; children: React.ReactNode }) {
  const colors = useColors();
  return (
    <View className="gap-2">
      <Text className="text-xs font-semibold uppercase tracking-wide" style={{ color: colors.textSubtle }}>
        {label}
      </Text>
      {children}
    </View>
  );
}

function Chip({
  label,
  selected,
  onPress,
}: {
  label: string;
  selected: boolean;
  onPress: () => void;
}) {
  const colors = useColors();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected }}
      className={cn('rounded-full border px-3 py-1.5')}
      style={{
        backgroundColor: selected ? colors.accent : colors.surfaceRaised,
        borderColor: selected ? colors.accent : colors.border,
      }}>
      <Text
        className="text-xs font-medium"
        style={{ color: selected ? colors.accentText : colors.textMuted }}>
        {label}
      </Text>
    </Pressable>
  );
}

function SearchField({
  placeholder,
  onSubmit,
  onChangeText,
  testID,
}: {
  placeholder: string;
  onSubmit: () => void;
  onChangeText: (value: string) => void;
  testID?: string;
}) {
  const colors = useColors();
  return (
    <View
      className="h-12 flex-1 flex-row items-center gap-2 rounded-2xl border px-4"
      style={{ backgroundColor: colors.surface, borderColor: colors.border }}>
      <Ionicons name="search" size={17} color={colors.textSubtle} />
      <TextInput
        testID={testID}
        placeholder={placeholder}
        placeholderTextColor={colors.textSubtle}
        onChangeText={onChangeText}
        onSubmitEditing={onSubmit}
        returnKeyType="search"
        className="flex-1 text-base"
        style={{ color: colors.text }}
      />
    </View>
  );
}

/** Horizontally scrolling row of shortcuts, used on the browse header. */
export function QuickFilters({
  options,
  value,
  onChange,
}: {
  options: { value: string; label: string }[];
  value: string;
  onChange: (next: string) => void;
}) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false}>
      <View className="flex-row gap-2 pr-4">
        {options.map((option) => (
          <Chip
            key={option.value}
            label={option.label}
            selected={value === option.value}
            onPress={() => onChange(option.value)}
          />
        ))}
      </View>
    </ScrollView>
  );
}