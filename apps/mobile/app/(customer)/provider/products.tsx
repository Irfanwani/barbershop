import { useMemo, useState } from 'react';
import { Image, Pressable, ScrollView, Text, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import {
  useCreateProductOrder,
  useOrderQuote,
  useProductCategories,
  useProvider,
  useShopShelf,
} from '@/api/hooks';
import { Button, Card, EmptyState, IconButton, useColors } from '@/components/ui';
import { FormError } from '@/components/field';
import type { BasketLine, ShopProduct } from '@/types/api';

/**
 * A shop's products, with a basket.
 *
 * Prices and stock come from the server and are never computed here. The basket
 * holds only product ids and quantities — the same rule bookings follow, and for
 * the same reason: a client that does the arithmetic is a client that will
 * eventually get it wrong.
 */
export default function ShopProductsScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();

  const providerId = Number(id);
  const shop = useProvider(providerId);
  const categories = useProductCategories();
  const [category, setCategory] = useState('all');
  const shelf = useShopShelf(
    Number.isFinite(providerId) ? providerId : null,
    category === 'all' ? {} : { category },
  );

  const [basket, setBasket] = useState<Record<number, number>>({});
  const [error, setError] = useState<string | null>(null);
  const create = useCreateProductOrder();

  const lines: BasketLine[] = useMemo(
    () => Object.entries(basket).map(([product, quantity]) => ({ product: Number(product), quantity })),
    [basket],
  );
  const quote = useOrderQuote(Number.isFinite(providerId) ? providerId : null, lines);
  const itemCount = lines.reduce((total, line) => total + line.quantity, 0);

  function add(row: ShopProduct) {
    const current = basket[row.product.id] ?? 0;
    // Never let the basket exceed what the shop actually has; the server would
    // refuse it anyway, and an error at the point of tapping is worse.
    if (current >= row.quantity) return;
    setBasket((state) => ({ ...state, [row.product.id]: current + 1 }));
    setError(null);
  }

  function remove(row: ShopProduct) {
    setBasket((state) => {
      const current = (state[row.product.id] ?? 0) - 1;
      if (current <= 0) {
        const { [row.product.id]: _gone, ...rest } = state;
        return rest;
      }
      return { ...state, [row.product.id]: current };
    });
  }

  async function placeOrder() {
    setError(null);
    try {
      const order = await create.mutateAsync({ provider: providerId, items: lines });
      setBasket({});
      router.push(`/orders/${order.reference}`);
    } catch (caught) {
      setError(errorMessage(caught, 'Could not place that order.'));
    }
  }

  return (
    <>
      <ScrollView
        style={{ backgroundColor: colors.background }}
        contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 120, gap: 16 }}>
        <IconButton name="arrow-back" label="Back" onPress={() => router.back()} className="self-start" />

        <View className="gap-1">
          <Text className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>
            {shop.data?.display_name ?? 'Shop'}
          </Text>
          {shop.data?.address ? (
            <Text className="text-sm" style={{ color: colors.textMuted }}>
              {shop.data.address}
            </Text>
          ) : null}
        </View>

        <View className="flex-row gap-2">
          <CategoryChip
            label="All"
            active={category === 'all'}
            onPress={() => setCategory('all')}
          />
          {categories.data?.map((entry) => (
            <CategoryChip
              key={entry.value}
              label={entry.label}
              active={category === entry.value}
              onPress={() => setCategory(entry.value)}
            />
          ))}
        </View>

        <FormError message={error} />

        {shelf.isLoading ? (
          <Text className="text-sm" style={{ color: colors.textMuted }}>
            Loading what this shop sells…
          </Text>
        ) : (shelf.data?.length ?? 0) === 0 ? (
          <EmptyState
            icon="bag-handle-outline"
            title="Nothing for sale here"
            body="This shop has not stocked any products yet."
          />
        ) : (
          shelf.data?.map((row) => (
            <ProductRow
              key={row.id}
              row={row}
              inBasket={basket[row.product.id] ?? 0}
              onAdd={() => add(row)}
              onRemove={() => remove(row)}
            />
          ))
        )}
      </ScrollView>

      {itemCount > 0 ? (
        <BasketBar
          itemCount={itemCount}
          totalDisplay={quote.data?.total_display ?? null}
          total={quote.data?.total ?? 0}
          busy={create.isPending}
          onCheckout={placeOrder}
          bottomInset={insets.bottom}
        />
      ) : null}
    </>
  );
}

function CategoryChip({
  label,
  active,
  onPress,
}: {
  label: string;
  active: boolean;
  onPress: () => void;
}) {
  const colors = useColors();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ selected: active }}
      className="rounded-full border px-3 py-1.5 active:opacity-70"
      style={{
        backgroundColor: active ? colors.accent : colors.surface,
        borderColor: active ? colors.accent : colors.border,
      }}>
      <Text
        className="text-xs font-semibold"
        style={{ color: active ? colors.accentText : colors.textMuted }}>
        {label}
      </Text>
    </Pressable>
  );
}

function ProductRow({
  row,
  inBasket,
  onAdd,
  onRemove,
}: {
  row: ShopProduct;
  inBasket: number;
  onAdd: () => void;
  onRemove: () => void;
}) {
  const colors = useColors();
  const { product } = row;

  return (
    <Card className="flex-row gap-3">
      {product.photo ? (
        <Image
          source={{ uri: product.photo }}
          style={{ width: 64, height: 64, borderRadius: 12 }}
          accessibilityIgnoresInvertColors
        />
      ) : (
        <View
          className="h-16 w-16 items-center justify-center rounded-xl"
          style={{ backgroundColor: colors.surfaceRaised }}>
          <Ionicons name="cube-outline" size={22} color={colors.textSubtle} />
        </View>
      )}

      <View className="flex-1 gap-1">
        <Text className="text-[15px] font-semibold" style={{ color: colors.text }}>
          {product.name}
        </Text>
        {product.brand ? (
          <Text className="text-xs" style={{ color: colors.textSubtle }}>
            {product.brand}
          </Text>
        ) : null}
        <View className="flex-row items-baseline gap-2">
          <Text className="text-sm font-semibold" style={{ color: colors.text }}>
            {product.price_display}
          </Text>
          {product.is_discounted ? (
            <Text className="text-xs line-through" style={{ color: colors.textSubtle }}>
              {product.compare_at_price_display}
            </Text>
          ) : null}
        </View>

        {!row.is_in_stock ? (
          <Text className="text-xs font-medium" style={{ color: colors.danger }}>
            Out of stock
          </Text>
        ) : (
          <View className="mt-1 flex-row items-center gap-3">
            {inBasket > 0 ? (
              <>
                <IconButton
                  name="remove-circle"
                  label={`Remove one ${product.name}`}
                  onPress={onRemove}
                  size={26}
                />
                <Text
                  className="text-sm font-bold"
                  style={{ color: colors.text }}
                  testID={`basket-count-${product.id}`}>
                  {inBasket}
                </Text>
              </>
            ) : null}
            <IconButton
              name="add-circle"
              label={`Add one ${product.name}`}
              onPress={onAdd}
              // Disabled at the shelf limit, not just at checkout: the shopper
              // should learn the shelf is empty before they reach payment.
              disabled={inBasket >= row.quantity}
              size={26}
            />
            <Text className="text-xs" style={{ color: colors.textSubtle }}>
              {row.quantity} left
            </Text>
          </View>
        )}
      </View>
    </Card>
  );
}

function BasketBar({
  itemCount,
  totalDisplay,
  total,
  busy,
  onCheckout,
  bottomInset,
}: {
  itemCount: number;
  totalDisplay: string | null;
  total: number;
  busy: boolean;
  onCheckout: () => void;
  bottomInset: number;
}) {
  const colors = useColors();

  return (
    <View
      className="absolute inset-x-0 bottom-0 flex-row items-center gap-3 border-t px-4 py-3"
      style={{ backgroundColor: colors.surface, borderColor: colors.border, paddingBottom: bottomInset + 12 }}>
      <View className="flex-1 gap-0.5">
        <Text className="text-xs" style={{ color: colors.textMuted }}>
          {itemCount} item{itemCount === 1 ? '' : 's'}
        </Text>
        {/* Priced by the server. While the quote is in flight we show the
            item count rather than a number we made up ourselves. */}
        <Text className="text-lg font-bold" style={{ color: colors.text }}>
          {totalDisplay ?? '—'}
        </Text>
      </View>
      <Button onPress={onCheckout} loading={busy} disabled={total === 0} testID="checkout-products">
        Checkout
      </Button>
    </View>
  );
}
