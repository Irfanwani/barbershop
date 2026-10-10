import { Text, TextInput, View, type TextInputProps } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { forwardRef, useState } from 'react';

import { cn } from '@/lib/cn';
import { useColors } from '@/components/ui';

type FieldProps = TextInputProps & {
  label?: string;
  error?: string | null;
  hint?: string;
  icon?: keyof typeof Ionicons.glyphMap;
};

export const Field = forwardRef<TextInput, FieldProps>(function Field(
  { label, error, hint, icon, className, style, secureTextEntry, ...props },
  ref,
) {
  const colors = useColors();
  const [focused, setFocused] = useState(false);
  const [revealed, setRevealed] = useState(false);

  const isPassword = Boolean(secureTextEntry);

  return (
    <View className="gap-1.5">
      {label ? (
        <Text className="text-sm font-medium" style={{ color: colors.textMuted }}>
          {label}
        </Text>
      ) : null}

      <View
        className={cn(
          'flex-row items-center gap-2 rounded-2xl border px-4 py-3',
          className,
        )}
        style={{
          backgroundColor: colors.surface,
          borderColor: error ? colors.danger : focused ? colors.accent : colors.border,
        }}>
        {icon ? <Ionicons name={icon} size={18} color={colors.textSubtle} /> : null}
        <TextInput
          ref={ref}
          style={[{ flex: 1, fontSize: 16, color: colors.text }, style]}
          placeholderTextColor={colors.textSubtle}
          secureTextEntry={isPassword && !revealed}
          onFocus={(event) => {
            setFocused(true);
            props.onFocus?.(event);
          }}
          onBlur={(event) => {
            setFocused(false);
            props.onBlur?.(event);
          }}
          accessibilityLabel={label ?? props.placeholder}
          {...props}
        />
        {isPassword ? (
          <Ionicons
            name={revealed ? 'eye-off-outline' : 'eye-outline'}
            size={18}
            color={colors.textSubtle}
            onPress={() => setRevealed((value) => !value)}
            accessibilityRole="button"
            accessibilityLabel={revealed ? 'Hide password' : 'Show password'}
          />
        ) : null}
      </View>

      {error ? (
        <Text className="text-xs" style={{ color: colors.danger }}>
          {error}
        </Text>
      ) : hint ? (
        <Text className="text-xs" style={{ color: colors.textSubtle }}>
          {hint}
        </Text>
      ) : null}
    </View>
  );
});

/** Banner shown when a request fails, above a form rather than inside it. */
export function FormError({ message }: { message?: string | null }) {
  const colors = useColors();
  if (!message) return null;
  return (
    <View
      className="flex-row items-start gap-2 rounded-2xl border px-4 py-3"
      style={{ backgroundColor: `${colors.danger}14`, borderColor: `${colors.danger}40` }}>
      <Ionicons name="alert-circle-outline" size={18} color={colors.danger} />
      <Text className="flex-1 text-sm" style={{ color: colors.danger }}>
        {message}
      </Text>
    </View>
  );
}