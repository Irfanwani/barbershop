import { Text, View } from 'react-native';

import { useColors } from '@/components/ui';

/** One number with a caption. Used in the provider dashboard's summary row. */
export function Stat({
  label,
  value,
  tone = 'default',
}: {
  label: string;
  value: string | number;
  tone?: 'default' | 'accent' | 'success' | 'danger';
}) {
  const colors = useColors();

  const valueColors = {
    default: colors.text,
    accent: colors.accent,
    success: colors.success,
    danger: colors.danger,
  };

  return (
    <View
      className="flex-1 items-center gap-0.5 rounded-2xl border px-2 py-3"
      style={{ backgroundColor: colors.surface, borderColor: colors.border }}>
      <Text className="text-xl font-bold" style={{ color: valueColors[tone] }}>
        {value}
      </Text>
      <Text className="text-2xs uppercase tracking-wide" style={{ color: colors.textSubtle }}>
        {label}
      </Text>
    </View>
  );
}