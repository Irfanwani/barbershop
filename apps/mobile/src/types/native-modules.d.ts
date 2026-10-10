/**
 * Type declarations for third-party native modules that ship no types.
 *
 * `react-native-razorpay` is untyped. Only the surface the checkout uses is
 * declared here, so a wrong option name is a compile error rather than a
 * payment sheet that silently does nothing.
 */

declare module 'react-native-razorpay' {
  interface RazorpayOptions {
    key: string;
    order_id?: string;
    amount?: number;
    currency?: string;
    name?: string;
    description?: string;
    prefill?: { contact?: string; email?: string };
    theme?: { color?: string };
  }

  const RazorpayCheckout: {
    open(options: RazorpayOptions): Promise<{ razorpay_payment_id?: string } | undefined>;
    close(): void;
  };

  export default RazorpayCheckout;
}
