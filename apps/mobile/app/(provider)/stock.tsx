import { useMemo, useState } from 'react';
import { Image, ScrollView, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import { useMyShelf, usePopularProducts, useSetStock } from '@/api/hooks';
import { Button, Card, Divider, EmptyState, IconButton, useColors } from '@/components/ui';
import { Field, FormError } from '@/components/field';
import type { Product } from '@/types/api';

/**
 * What this shop has on its shelf.
 *
 * Products are the platform's catalogue; what a shop sells, and how much, is
 * this shop's business. So this screen is a shelf over a fixed catalogue rather
 * than a product editor — the shop chooses quantities, not the catalogue.
 */
export default function StockScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();

  const shelf = useMyShelf();
  const catalogue = usePopularProducts();
  const setStock = useSetStock();

  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState<Product | null>(null);
  const [quantity, setQuantity] = useState('0');

  const stockedIds = useMemo(
    () => new Set((shelf.data ?? []).map((row) => row.product.id)),
    [shelf.data],
  );

  function startAdding(product: Product) {
    setAdding(product);
    setQuantity('0');
    setError(null);
  }

  async function save() {
    if (!adding) return;
    const parsed = Number(quantity);
    if (!Number.isInteger(parsed) || parsed < 0) {
      setError('Stock has to be a whole number, zero or more.');
      return;
    }

    setError(null);
    try {
      await setStock.mutateAsync({ product: adding.id, quantity: parsed });
      setAdding(null);
    } catch (caught) {
      setError(errorMessage(caught, 'Could not save that stock level.'));
    }
  }

  const rows = shelf.data ?? [];

  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 32, gap: 16 }}>
      <Text className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>
        Stock
      </Text>
      <Text className="-mt-3 text-sm" style={{ color: colors.textMuted }}>
        What customers can buy here. Products come from the BarberShop catalogue; the
        quantities are yours.
      </Text>

      <FormError message={error} />

      {adding ? (
        <Card className="gap-3">
          <Text className="text-base font-semibold" style={{ color: colors.text }}>
            {adding.name}
          </Text>
          <Field
            label="How many"
            placeholder="0"
            keyboardType="number-pad"
            value={quantity}
            onChangeText={setQuantity}
            hint="Zero hides it from your shelf without deleting it."
            testID="stock-quantity"
          />
          <View className="flex-row gap-2">
            <View className="flex-1">
              <Button onPress={save} loading={setStock.isPending} testID="stock-save">
                Save
              </Button>
            </View>
            <IconButton
              name="close"
              label="Cancel"
              onPress={() => setAdding(null)}
              className="h-12 w-12 rounded-xl border"
            />
          </View>
        </Card>
      ) : null}

      <View className="gap-2">
        <Text
          className="px-1 text-xs font-semibold uppercase tracking-wide"
          style={{ color: colors.textSubtle }}>
          On your shelf
        </Text>

        {shelf.isLoading ? (
          <Text className="text-sm" style={{ color: colors.textMuted }}>
            Loading your stock…
          </Text>
        ) : rows.length === 0 ? (
          <EmptyState
            icon="cube-outline"
            title="Your shelf is empty"
            body="Add something from the catalogue below and customers will be able to buy it."
          />
        ) : (
          <Card>
            {rows.map((row, index) => (
              <View key={row.id}>
                {index > 0 ? <Divider className="my-3" /> : null}
                <View className="flex-row items-center gap-3">
                  {row.product.photo ? (
                    <Image
                      source={{ uri: row.product.photo }}
                      style={{ width: 44, height: 44, borderRadius: 10 }}
                      accessibilityIgnoresInvertColors
                    />
                  ) : (
                    <View
                      className="h-11 w-11 items-center justify-center rounded-lg"
                      style={{ backgroundColor: colors.surfaceRaised }}>
                      <Ionicons name="cube-outline" size={18} color={colors.textSubtle} />
                    </View>
                  )}

                  <View className="flex-1">
                    <Text className="text-[15px] font-medium" style={{ color: colors.text }}>
                      {row.product.name}
                    </Text>
                    <Text className="text-xs" style={{ color: colors.textSubtle }}>
                      {row.product.price_display} ·{' '}
                      {row.is_available ? `${row.quantity} in stock` : 'hidden'}
                    </Text>
                  </View>

                  <IconButton
                    name="create-outline"
                    label={`Change stock for ${row.product.name}`}
                    onPress={() => startAdding(row.product)}
                  />
                </View>
              </View>
            ))}
          </Card>
        )}
      </View>

      <View className="gap-2">
        <Text
          className="px-1 text-xs font-semibold uppercase tracking-wide"
          style={{ color: colors.textSubtle }}>
          From the catalogue
        </Text>

        {catalogue.data?.length ? (
          catalogue.data
            .filter((product) => !stockedIds.has(product.id))
            .map((product) => (
              <Card key={product.id} className="flex-row items-center gap-3">
                <View className="flex-1">
                  <Text className="text-[15px] font-medium" style={{ color: colors.text }}>
                    {product.name}
                  </Text>
                  <Text className="text-xs" style={{ color: colors.textSubtle }}>
                    {product.brand} · {product.price_display}
                  </Text>
                </View>
                <Button
                  variant="secondary"
                  onPress={() => startAdding(product)}
                  testID={`add-${product.id}`}>
                  Add
                </Button>
              </Card>
            ))
        ) : (
          <Text className="text-sm" style={{ color: colors.textMuted }}>
            No products available.
          </Text>
        )}
      </View>
    </ScrollView>
  );
}
