import { useState } from 'react';
import { ScrollView, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import { isUnnamed } from '@/lib/money';
import { useMyStaff, useRetireStaff, useSaveStaff } from '@/api/hooks';
import { Button, Card, Divider, EmptyState, IconButton, useColors } from '@/components/ui';
import { Field, FormError } from '@/components/field';
import type { StaffMember } from '@/types/api';

/**
 * Who works here.
 *
 * The shop's capacity is the number of people on this list, which is why adding
 * someone here immediately lets the shop take another booking at the same time.
 * That connection is stated on the screen: a provider who does not realise it
 * will assume the list is only for display.
 *
 * Someone who leaves is retired rather than deleted — their name stays on the
 * bookings they worked, which is the whole point of naming them.
 */
export default function StaffScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();

  const staff = useMyStaff();
  const save = useSaveStaff();
  const retire = useRetireStaff();

  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('');
  const [bio, setBio] = useState('');
  const [error, setError] = useState<string | null>(null);

  const active = (staff.data ?? []).filter((member) => member.is_active);
  const retired = (staff.data ?? []).filter((member) => !member.is_active);
  const placeholders = active.filter(isUnnamed);

  async function submit() {
    setError(null);
    try {
      await save.mutateAsync({ body: { name: name.trim(), bio: bio.trim() } });
      setName('');
      setBio('');
      setAdding(false);
    } catch (caught) {
      setError(errorMessage(caught, 'Could not add that person.'));
    }
  }

  async function confirmRetire(member: StaffMember) {
    setError(null);
    try {
      await retire.mutateAsync(member.id);
    } catch (caught) {
      setError(errorMessage(caught, 'Could not remove that person.'));
    }
  }

  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 32, gap: 16 }}
      keyboardShouldPersistTaps="handled">
      <IconButton name="arrow-back" label="Back" onPress={() => router.back()} className="self-start" />

      <View className="gap-1">
        <Text className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>
          Your team
        </Text>
        <Text className="text-sm" style={{ color: colors.textMuted }}>
          You can take {active.length} {active.length === 1 ? 'booking' : 'bookings'} at once — one
          for each person on this list.
        </Text>
      </View>

      <FormError message={error} />

      {placeholders.length > 0 ? (
        <Card className="gap-1">
          <Text className="text-sm font-semibold" style={{ color: colors.warning }}>
            {placeholders.length === 1 ? 'One person is' : `${placeholders.length} people are`} still
            unnamed
          </Text>
          <Text className="text-xs leading-4" style={{ color: colors.textSubtle }}>
            These came from the number you had set before you could name your team. Rename them so
            customers can book them by name.
          </Text>
        </Card>
      ) : null}

      {staff.isLoading ? (
        <Text className="text-sm" style={{ color: colors.textMuted }}>
          Loading your team…
        </Text>
      ) : (staff.data?.length ?? 0) === 0 ? (
        <EmptyState
          icon="people-outline"
          title="Nobody named yet"
          body="Add the people who work here so customers can pick the barber they want. Until you do, your shop takes one booking at a time."
          action={
            <Button onPress={() => setAdding(true)} testID="add-first-staff">
              Add someone
            </Button>
          }
        />
      ) : (
        <View className="gap-3">
          {active.map((member) => (
            <StaffRow key={member.id} member={member} onRetire={() => confirmRetire(member)} />
          ))}
        </View>
      )}

      {!adding ? (
        <Button variant="ghost" onPress={() => setAdding(true)} testID="add-staff">
          Add someone
        </Button>
      ) : (
        <Card className="gap-3">
          <Text className="text-base font-semibold" style={{ color: colors.text }}>
            New team member
          </Text>
          <Field
            label="Name"
            value={name}
            onChangeText={setName}
            placeholder="Ravi Kumar"
            autoCapitalize="words"
            testID="staff-name"
          />
          <Field
            label="About them (optional)"
            value={bio}
            onChangeText={setBio}
            placeholder="Ten years cutting hair, specialising in curls."
            multiline
            testID="staff-bio"
          />
          <View className="flex-row gap-2">
            <Button
              className="flex-1"
              onPress={() => setAdding(false)}
              testID="cancel-add-staff">
              Cancel
            </Button>
            <Button
              className="flex-1"
              onPress={submit}
              loading={save.isPending}
              disabled={name.trim().length === 0}
              testID="save-staff">
              Add
            </Button>
          </View>
        </Card>
      )}

      {retired.length > 0 ? (
        <View className="gap-2">
          <Text className="px-1 text-xs font-semibold uppercase tracking-wide" style={{ color: colors.textSubtle }}>
            No longer here
          </Text>
          <Card>
            {retired.map((member, index) => (
              <View key={member.id}>
                {index > 0 ? <Divider className="my-3" /> : null}
                <View className="flex-row items-center justify-between gap-3">
                  <Text className="text-sm" style={{ color: colors.textMuted }}>
                    {member.name}
                  </Text>
                  <Ionicons name="archive-outline" size={16} color={colors.textSubtle} />
                </View>
              </View>
            ))}
          </Card>
          <Text className="px-1 text-xs" style={{ color: colors.textSubtle }}>
            Kept so the bookings they worked still say who did them.
          </Text>
        </View>
      ) : null}
    </ScrollView>
  );
}

function StaffRow({ member, onRetire }: { member: StaffMember; onRetire: () => void }) {
  const colors = useColors();

  return (
    <Card className="gap-3">
      <View className="flex-row items-start justify-between gap-3">
        <View className="flex-1 gap-1">
          <Text className="text-base font-semibold" style={{ color: colors.text }}>
            {member.name}
          </Text>
          {isUnnamed(member) ? (
            <Text className="text-xs" style={{ color: colors.warning }}>
              Unnamed — tap rename to add their name
            </Text>
          ) : null}
          {member.bio ? (
            <Text className="text-sm leading-5" style={{ color: colors.textMuted }}>
              {member.bio}
            </Text>
          ) : null}
        </View>
        <Button variant="ghost" onPress={onRetire} testID={`retire-${member.id}`}>
          Remove
        </Button>
      </View>
    </Card>
  );
}