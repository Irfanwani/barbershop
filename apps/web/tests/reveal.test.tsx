import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Reveal } from '@/components/Reveal';

/**
 * jsdom has no IntersectionObserver, which is why `Reveal` falls back to
 * "visible" in the rest of the suite. This fake lets us exercise the real path
 * too: content waits for the observer, then reveals once and stays revealed.
 */
class FakeIntersectionObserver {
  static instances: FakeIntersectionObserver[] = [];

  root: Element | Document | null = null;
  rootMargin = '0px';
  thresholds: number[] = [];
  disconnect = vi.fn();
  private callback: IntersectionObserverCallback;
  private elements = new Set<Element>();

  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback;
    FakeIntersectionObserver.instances.push(this);
  }

  observe = (element: Element) => {
    this.elements.add(element);
  };

  unobserve = (element: Element) => {
    this.elements.delete(element);
  };

  takeRecords = (): IntersectionObserverEntry[] => [];

  trigger(isIntersecting: boolean) {
    const target = [...this.elements][0];
    if (!target) throw new Error('No element was observed');

    this.callback(
      [{ isIntersecting, target } as IntersectionObserverEntry],
      this as unknown as IntersectionObserver,
    );
  }
}

const original = globalThis.IntersectionObserver;

afterEach(() => {
  FakeIntersectionObserver.instances = [];
  if (original) {
    globalThis.IntersectionObserver = original;
  } else {
    Reflect.deleteProperty(globalThis, 'IntersectionObserver');
  }
});

describe('scroll reveal', () => {
  it('reveals its content once it enters the viewport', () => {
    globalThis.IntersectionObserver =
      FakeIntersectionObserver as unknown as typeof IntersectionObserver;

    render(
      <Reveal>
        <p>Revealed copy</p>
      </Reveal>,
    );

    const wrapper = screen.getByText('Revealed copy').parentElement;
    const observer = FakeIntersectionObserver.instances[0];
    if (!observer) throw new Error('Reveal never created an observer');
    expect(wrapper).not.toHaveClass('is-visible');

    act(() => observer.trigger(true));

    expect(wrapper).toHaveClass('is-visible');
    expect(observer.disconnect).toHaveBeenCalled();
  });
});
