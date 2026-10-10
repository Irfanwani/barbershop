import { Pressable, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

import { Divider, useColors } from '@/components/ui';

export type SettingsRow = {
  icon: keyof typeof Ionicons.glyphMap;
  title: string;
  subtitle?: string;
  value?: string;
  onPress?: () => void;
  danger?: boolean;
  /** Rendered on the right instead of the chevron. */
  accessory?: React.ReactNode;
};

/** A settings list, split by optional section heading. */
export function SettingsList({
  rows,
  title,
}: {
  rows: SettingsRow[];
  title?: string;
}) {
  const colors = useColors();

  return (
    <View className="gap-2">
      {title ? (
        <Text
          className="px-1 text-xs font-semibold uppercase tracking-wide"
          style={{ color: colors.textSubtle }}>
          {title}
        </Text>
      ) : null}

      <View className="overflow-hidden rounded-2xl border" style={{ backgroundColor: colors.surface, borderColor: colors.border }}>
        {rows.map((row, index) => (
          <View key={row.title}>
            {index > 0 ? <Divider /> : null}
            <Pressable
              onPress={row.onPress}
              accessibilityRole={row.onPress ? 'button' : undefined}
              accessibilityLabel={row.title}
              disabled={!row.onPress}
              className="flex-row items-center gap-3 px-4 py-3.5 active:opacity-70">
              <View
                className="h-9 w-9 items-center justify-center rounded-xl"
                style={{ backgroundColor: colors.surfaceRaised }}>
                <Ionicons
                  name={row.icon}
                  size={17}
                  color={row.danger ? colors.danger : colors.textMuted}
                />
              </View>

              <View className="flex-1 gap-0.5">
                <Text
                  className="text-[15px] font-medium"
                  style={{ color: row.danger ? colors.danger : colors.text }}>
                  {row.title}
                </Text>
                {row.subtitle ? (
                  <Text className="text-xs" style={{ color: colors.textSubtle }}>
                    {row.subtitle}
                  </Text>
                ) : null}
              </View>

              {row.value ? (
                <Text className="text-sm" style={{ color: colors.textMuted }}>
                  {row.value}
                </Text>
              ) : null}
              {row.accessory}
              {row.onPress ? (
                <Ionicons name="chevron-forward" size={16} color={colors.textSubtle} />
              ) : null}
            </Pressable>
          </View>
        ))}
      </View>
    </View>
  );
}