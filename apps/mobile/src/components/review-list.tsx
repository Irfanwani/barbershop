import { Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

import { Card, Divider, EmptyState, useColors } from '@/components/ui';
import type { Review, ReviewSummary } from '@/types/api';

/**
 * Reviews for a shop, with the average at the top.
 *
 * The average is the provider's cached rating, not one computed from the page on
 * screen — a page of reviews is not the whole history, and averaging what
 * happens to be loaded gives a number that changes as you scroll.
 */
export function ReviewList({
  reviews,
  summary,
  loading = false,
  emptyHint,
}: {
  reviews: Review[];
  summary?: ReviewSummary;
  loading?: boolean;
  emptyHint?: string;
}) {
  const colors = useColors();

  if (loading) {
    return (
      <Text className="text-sm" style={{ color: colors.textMuted }}>
        Loading reviews…
      </Text>
    );
  }

  if (reviews.length === 0) {
    return (
      <EmptyState
        icon="chatbubbles-outline"
        title="No reviews yet"
        body={emptyHint ?? 'Be the first to say how it went.'}
      />
    );
  }

  return (
    <View className="gap-3">
      {summary && summary.total > 0 ? (
        <View className="flex-row items-center gap-2 px-1">
          <Ionicons name="star" size={16} color="#F59E0B" />
          <Text className="text-base font-semibold" style={{ color: colors.text }}>
            {summary.average?.toFixed(1)}
          </Text>
          <Text className="text-xs" style={{ color: colors.textSubtle }}>
            from {summary.total} {summary.total === 1 ? 'review' : 'reviews'}
          </Text>
        </View>
      ) : null}

      <Card>
        {reviews.map((review, index) => (
          <View key={review.id}>
            {index > 0 ? <Divider className="my-3" /> : null}
            <View className="gap-1.5">
              <View className="flex-row items-center justify-between">
                <Text className="text-sm font-semibold" style={{ color: colors.text }}>
                  {review.customer_display_name}
                </Text>
                <View className="flex-row gap-0.5">
                  {Array.from({ length: review.rating }).map((_, star) => (
                    <Ionicons key={star} name="star" size={11} color="#F59E0B" />
                  ))}
                </View>
              </View>

              {review.comment ? (
                <Text className="text-sm leading-5" style={{ color: colors.textMuted }}>
                  {review.comment}
                </Text>
              ) : null}

              {review.provider_reply ? (
                <View
                  className="mt-1 rounded-xl px-3 py-2"
                  style={{ backgroundColor: colors.surface }}>
                  <Text className="text-2xs font-semibold uppercase" style={{ color: colors.textSubtle }}>
                    {review.provider_name} replied
                  </Text>
                  <Text className="text-sm" style={{ color: colors.textMuted }}>
                    {review.provider_reply}
                  </Text>
                </View>
              ) : null}
            </View>
          </View>
        ))}
      </Card>
    </View>
  );
}