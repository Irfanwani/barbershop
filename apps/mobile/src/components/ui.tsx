import type { ReactNode } from 'react';
import { ActivityIndicator, Pressable, Text, View , useColorScheme } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

import { cn } from '@/lib/cn';

/**
 * Light and dark, decided once and shared.
 *
 * The old apps each carried their own colour scheme object, and the two drifted
 * until a screen looked correct on one and broken on the other. Keeping the two
 * palettes side by side here makes an omission obvious.
 */
const palette = {
  light: {
    background: '#FFFFFF',
    surface: '#F8FAFC',
    surfaceRaised: '#FFFFFF',
    border: '#E2E8F0',
    text: '#0F172A',
    textMuted: '#64748B',
    textSubtle: '#94A3B8',
    accent: '#F97316',
    accentText: '#FFFFFF',
    danger: '#DC2626',
    success: '#059669',
    warning: '#B45309',
  },
  dark: {
    background: '#0F172A',
    surface: '#1E293B',
    surfaceRaised: '#334155',
    border: '#334155',
    text: '#F8FAFC',
    textMuted: '#94A3B8',
    textSubtle: '#64748B',
    accent: '#FB923C',
    accentText: '#0F172A',
    danger: '#F87171',
    success: '#34D399',
    warning: '#FBBF24',
  },
};

export type Colors = typeof palette.light;

export function useColors(): Colors {
  return useColorScheme() === 'dark' ? palette.dark : palette.light;
}

type ButtonProps = {
  /** Optional so a button can be icon-only. Always pass `accessibilityLabel` then. */
  children?: ReactNode;
  onPress?: () => void;
  accessibilityLabel?: string;
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  loading?: boolean;
  disabled?: boolean;
  className?: string;
  icon?: keyof typeof Ionicons.glyphMap;
  testID?: string;
};

export function Button({
  children,
  onPress,
  variant = 'primary',
  loading = false,
  disabled = false,
  className,
  icon,
  testID,
  accessibilityLabel,
}: ButtonProps) {
  const colors = useColors();
  const isDisabled = disabled || loading;

  const backgrounds = {
    primary: colors.accent,
    secondary: colors.surfaceRaised,
    ghost: 'transparent',
    danger: colors.danger,
  };
  const foregrounds = {
    primary: colors.accentText,
    secondary: colors.text,
    ghost: colors.accent,
    danger: '#FFFFFF',
  };

  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      disabled={isDisabled}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityState={{ disabled: isDisabled, busy: loading }}
      className={cn(
        'flex-row items-center justify-center gap-2 rounded-2xl px-5 py-3.5',
        variant === 'secondary' && 'border',
        !isDisabled && 'active:opacity-80',
        isDisabled && 'opacity-50',
        className,
      )}
      style={{
        backgroundColor: backgrounds[variant],
        borderColor: variant === 'secondary' ? colors.border : 'transparent',
      }}>
      {loading ? (
        <ActivityIndicator color={foregrounds[variant]} size="small" />
      ) : (
        <>
          {icon ? <Ionicons name={icon} size={18} color={foregrounds[variant]} /> : null}
          {children ? (
            <Text className="text-base font-semibold" style={{ color: foregrounds[variant] }}>
              {children}
            </Text>
          ) : null}
        </>
      )}
    </Pressable>
  );
}

type IconButtonProps = {
  name: keyof typeof Ionicons.glyphMap;
  onPress?: () => void;
  size?: number;
  color?: string;
  label: string;
  className?: string;
  disabled?: boolean;
};

export function IconButton({
  name,
  onPress,
  size = 22,
  color,
  label,
  className,
  disabled = false,
}: IconButtonProps) {
  const colors = useColors();
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled }}
      className={cn(
        'h-10 w-10 items-center justify-center rounded-full active:opacity-70',
        disabled && 'opacity-40',
        className,
      )}>
      <Ionicons name={name} size={size} color={color ?? colors.text} />
    </Pressable>
  );
}

type CardProps = { children: ReactNode; className?: string; onPress?: () => void };

export function Card({ children, className, onPress }: CardProps) {
  const colors = useColors();
  const content = (
    <View
      className={cn('rounded-2xl border p-4', className)}
      style={{ backgroundColor: colors.surface, borderColor: colors.border }}>
      {children}
    </View>
  );
  if (!onPress) return content;
  return (
    <Pressable onPress={onPress} accessibilityRole="button" className="active:opacity-80">
      {content}
    </Pressable>
  );
}

type BadgeTone = 'neutral' | 'accent' | 'success' | 'danger' | 'warning';

type BadgeProps = { children: ReactNode; tone?: BadgeTone };

export function Badge({ children, tone = 'neutral' }: BadgeProps) {
  const colors = useColors();
  const tones = {
    neutral: { background: colors.surfaceRaised, color: colors.textMuted },
    accent: { background: colors.accent, color: colors.accentText },
    success: { background: colors.success, color: '#FFFFFF' },
    danger: { background: colors.danger, color: '#FFFFFF' },
    // Amber reads as "not yet" without reading as an error.
    warning: { background: colors.warning, color: '#FFFFFF' },
  };
  const selected = tones[tone];
  return (
    <View
      className="self-start rounded-full px-2.5 py-1"
      style={{ backgroundColor: selected.background }}>
      <Text className="text-2xs font-semibold uppercase tracking-wide" style={{ color: selected.color }}>
        {children}
      </Text>
    </View>
  );
}

type EmptyStateProps = {
  icon: keyof typeof Ionicons.glyphMap;
  title: string;
  body?: string;
  action?: ReactNode;
};

export function EmptyState({ icon, title, body, action }: EmptyStateProps) {
  const colors = useColors();
  return (
    <View className="items-center gap-3 px-8 py-16">
      <View
        className="h-16 w-16 items-center justify-center rounded-full"
        style={{ backgroundColor: colors.surface }}>
        <Ionicons name={icon} size={28} color={colors.textSubtle} />
      </View>
      <Text className="text-center text-lg font-semibold" style={{ color: colors.text }}>
        {title}
      </Text>
      {body ? (
        <Text className="text-center text-sm leading-5" style={{ color: colors.textMuted }}>
          {body}
        </Text>
      ) : null}
      {action}
    </View>
  );
}

export function Divider({ className }: { className?: string }) {
  const colors = useColors();
  return <View className={cn('h-px w-full', className)} style={{ backgroundColor: colors.border }} />;
}

export function Screen({
  children,
  className,
  _scroll = false,
}: {
  children: ReactNode;
  className?: string;
  _scroll?: boolean;
}) {
  const colors = useColors();
  return (
    <View className={cn('flex-1', className)} style={{ backgroundColor: colors.background }}>
      {children}
    </View>
  );
}