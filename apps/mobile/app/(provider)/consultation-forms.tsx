/**
 * Writing a consultation form.
 *
 * A barber needs to know things before somebody sits down — have you had colour
 * before, is there a patch you would rather I did not touch — and a
 * 500-character notes box is not how anybody asks that.
 *
 * A form with nothing attached to a service is never shown, so attaching is the
 * step that makes one live. The screen says so rather than letting somebody
 * save a form and wonder why it never appears.
 */

import { useState } from 'react';
import { ScrollView, Text, View, Pressable } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import {
  useCreateConsultationForm,
  useMyConsultationForms,
  useMyServices,
  useMyShop,
} from '@/api/hooks';
import { Button, Card, Divider, EmptyState, useColors } from '@/components/ui';
import { Field, FormError } from '@/components/field';

type Kind = 'short_text' | 'long_text' | 'choice' | 'yes_no';

interface Draft {
  label: string;
  kind: Kind;
  choices: string;
  is_required: boolean;
  is_sensitive: boolean;
}

const KINDS: { value: Kind; label: string }[] = [
  { value: 'short_text', label: 'Short answer' },
  { value: 'long_text', label: 'Longer answer' },
  { value: 'yes_no', label: 'Yes or no' },
  { value: 'choice', label: 'Pick one' },
];

const blankQuestion = (): Draft => ({
  label: '',
  kind: 'short_text',
  choices: '',
  is_required: true,
  is_sensitive: false,
});

export default function ConsultationFormsScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();

  const shop = useMyShop();
  const forms = useMyConsultationForms();
  const services = useMyServices();
  const create = useCreateConsultationForm();

  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [serviceIds, setServiceIds] = useState<number[]>([]);
  const [questions, setQuestions] = useState<Draft[]>([blankQuestion()]);
  const [error, setError] = useState<string | null>(null);

  const menu = services.data ?? [];

  function patch(index: number, next: Partial<Draft>) {
    setQuestions((current) =>
      current.map((question, i) => (i === index ? { ...question, ...next } : question)),
    );
  }

  async function submit() {
    setError(null);

    if (!name.trim()) {
      setError('Give the form a name.');
      return;
    }
    const blank = questions.findIndex((question) => !question.label.trim());
    if (blank !== -1) {
      setError(`Question ${blank + 1} needs a label.`);
      return;
    }
    const choiceless = questions.findIndex(
      (question) => question.kind === 'choice' && !question.choices.trim(),
    );
    if (choiceless !== -1) {
      setError(`Question ${choiceless + 1} needs some choices, separated by commas.`);
      return;
    }
    if (serviceIds.length === 0) {
      // Not a warning. A form attached to nothing is never asked, so saving it
      // looks successful and then does nothing forever.
      setError('Attach this to at least one service, or it will never be asked.');
      return;
    }

    try {
      await create.mutateAsync({
        name: name.trim(),
        description: description.trim(),
        service_ids: serviceIds,
        questions: questions.map((question) => ({
          label: question.label.trim(),
          kind: question.kind,
          choices:
            question.kind === 'choice'
              ? question.choices
                  .split(',')
                  .map((choice) => choice.trim())
                  .filter(Boolean)
              : [],
          is_required: question.is_required,
          is_sensitive: question.is_sensitive,
        })),
      });
      setOpen(false);
      setName('');
      setDescription('');
      setServiceIds([]);
      setQuestions([blankQuestion()]);
    } catch (caught) {
      setError(errorMessage(caught, 'Could not save that form.'));
    }
  }

  return (
    <SafeAreaView className="flex-1" style={{ backgroundColor: colors.background }} edges={['top']}>
      <ScrollView
        contentContainerStyle={{ padding: 16, gap: 16, paddingBottom: insets.bottom + 32 }}>
        <View className="gap-1">
          <Text className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>
            Consultation forms
          </Text>
          <Text className="text-sm" style={{ color: colors.textMuted }}>
            Ask what you need to know before somebody sits in your chair.
          </Text>
        </View>

        {shop.data?.display_name ? (
          <Card>
            <Text className="text-sm" style={{ color: colors.text }}>
              {shop.data.display_name}
            </Text>
            <Text className="text-xs" style={{ color: colors.textSubtle }}>
              Attached to {menu.length === 0 ? 'no services yet' : `${menu.length} services`}
            </Text>
          </Card>
        ) : null}

        {forms.isError ? (
          <Card>
            <Text className="text-sm" style={{ color: colors.danger }}>
              {errorMessage(forms.error, 'Could not load your forms.')}
            </Text>
          </Card>
        ) : null}

        {open ? (
          <Card className="gap-3">
            <Field
              label="Form name"
              placeholder="Before we start"
              value={name}
              onChangeText={setName}
              testID="form-name"
            />
            <Field
              label="Tell the customer why"
              placeholder="So we get the shade right."
              value={description}
              onChangeText={setDescription}
              multiline
              numberOfLines={2}
              testID="form-description"
            />

            <View className="gap-2">
              <Text className="text-sm font-medium" style={{ color: colors.text }}>
                Ask this when booking
              </Text>
              {menu.map((service) => {
                const on = serviceIds.includes(service.id);
                return (
                  <Pressable
                    key={service.id}
                    onPress={() =>
                      setServiceIds((current) =>
                        on ? current.filter((id) => id !== service.id) : [...current, service.id],
                      )
                    }
                    accessibilityRole="checkbox"
                    accessibilityState={{ checked: on }}
                    testID={`attach-service-${service.id}`}
                    className="flex-row items-center gap-3 rounded-2xl border px-4 py-3"
                    style={{
                      backgroundColor: on ? `${colors.accent}12` : colors.surface,
                      borderColor: on ? colors.accent : colors.border,
                    }}>
                    <Ionicons
                      name={on ? 'checkbox' : 'square-outline'}
                      size={20}
                      color={on ? colors.accent : colors.textSubtle}
                    />
                    <Text className="text-sm" style={{ color: colors.text }}>
                      {service.name}
                    </Text>
                  </Pressable>
                );
              })}
            </View>

            <Divider />

            {questions.map((question, index) => (
              <View key={index} className="gap-2">
                <Field
                  label={`Question ${index + 1}`}
                  placeholder="Have you had colour before?"
                  value={question.label}
                  onChangeText={(next) => patch(index, { label: next })}
                  testID={`question-label-${index}`}
                />

                <View className="flex-row flex-wrap gap-2">
                  {KINDS.map((kind) => (
                    <Pressable
                      key={kind.value}
                      onPress={() => patch(index, { kind: kind.value })}
                      accessibilityRole="radio"
                      accessibilityState={{ selected: question.kind === kind.value }}
                      testID={`question-kind-${index}-${kind.value}`}>
                      <View
                        className="rounded-full px-3 py-1.5"
                        style={{
                          backgroundColor:
                            question.kind === kind.value ? colors.accent : colors.surface,
                        }}>
                        <Text
                          className="text-xs font-medium"
                          style={{
                            color:
                              question.kind === kind.value ? colors.accentText : colors.textMuted,
                          }}>
                          {kind.label}
                        </Text>
                      </View>
                    </Pressable>
                  ))}
                </View>

                {question.kind === 'choice' ? (
                  <Field
                    label="Choices"
                    hint="Separated by commas."
                    placeholder="Just tidy, Not too much, Take it all off"
                    value={question.choices}
                    onChangeText={(next) => patch(index, { choices: next })}
                    testID={`question-choices-${index}`}
                  />
                ) : null}

                <Pressable
                  onPress={() => patch(index, { is_required: !question.is_required })}
                  accessibilityRole="switch"
                  accessibilityState={{ checked: question.is_required }}
                  testID={`question-required-${index}`}
                  className="flex-row items-center justify-between">
                  <Text className="text-sm" style={{ color: colors.text }}>
                    Needed to book in
                  </Text>
                  <Ionicons
                    name={question.is_required ? 'checkbox' : 'square-outline'}
                    size={20}
                    color={question.is_required ? colors.accent : colors.textSubtle}
                  />
                </Pressable>

                <Pressable
                  onPress={() => patch(index, { is_sensitive: !question.is_sensitive })}
                  accessibilityRole="switch"
                  accessibilityState={{ checked: question.is_sensitive }}
                  testID={`question-sensitive-${index}`}
                  className="flex-row items-center justify-between">
                  <View className="flex-1 pr-3">
                    <Text className="text-sm" style={{ color: colors.text }}>
                      Private to me
                    </Text>
                    <Text className="text-xs" style={{ color: colors.textSubtle }}>
                      Health and allergy answers. Not shown to anyone else, and not
                      read back to the customer.
                    </Text>
                  </View>
                  <Ionicons
                    name={question.is_sensitive ? 'checkbox' : 'square-outline'}
                    size={20}
                    color={question.is_sensitive ? colors.accent : colors.textSubtle}
                  />
                </Pressable>

                {questions.length > 1 ? (
                  <Button
                    variant="ghost"
                    onPress={() =>
                      setQuestions((current) => current.filter((_, i) => i !== index))
                    }
                    testID={`remove-question-${index}`}>
                    Remove question {index + 1}
                  </Button>
                ) : null}
              </View>
            ))}

            <Button
              variant="secondary"
              onPress={() => setQuestions((current) => [...current, blankQuestion()])}
              testID="add-question">
              Add another question
            </Button>

            <FormError message={error} />

            <Button onPress={() => void submit()} loading={create.isPending} testID="save-form">
              Save form
            </Button>
          </Card>
        ) : (
          <Button onPress={() => setOpen(true)} testID="new-form">
            Write a consultation form
          </Button>
        )}

        {(forms.data ?? []).map((form) => (
          <Card key={form.id}>
            <View className="flex-row items-center justify-between">
              <Text className="text-base font-semibold" style={{ color: colors.text }}>
                {form.name}
              </Text>
              {!form.is_active ? (
                <Text className="text-xs" style={{ color: colors.textSubtle }}>
                  retired
                </Text>
              ) : null}
            </View>
            {form.description ? (
              <Text className="text-xs" style={{ color: colors.textSubtle }}>
                {form.description}
              </Text>
            ) : null}
            <Text className="text-xs" style={{ color: colors.textMuted }}>
              {form.questions.length} {form.questions.length === 1 ? 'question' : 'questions'} ·
              asked for {form.service_ids.length}{' '}
              {form.service_ids.length === 1 ? 'service' : 'services'}
            </Text>
            {form.service_ids.length === 0 ? (
              <Text className="text-xs font-medium" style={{ color: colors.warning }}>
                Attached to nothing, so it is never asked. Edit it to attach it to a
                service.
              </Text>
            ) : null}
            {form.questions.map((question) => (
              <View key={question.id} className="flex-row items-center justify-between">
                <Text className="text-sm" style={{ color: colors.text }}>
                  {question.label}
                </Text>
                {question.is_sensitive ? (
                  <Text className="text-2xs" style={{ color: colors.textSubtle }}>
                    private
                  </Text>
                ) : null}
              </View>
            ))}
          </Card>
        ))}

        {!forms.isLoading && (forms.data ?? []).length === 0 && !open ? (
          <EmptyState
            icon="help-circle-outline"
            title="No forms yet"
            body="A form attached to a service is asked when somebody books it. It is the difference between knowing what they need and finding out in the chair."
          />
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}