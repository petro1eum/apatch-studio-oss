/** Match Python str.split(), used by the lock authority, including Unicode spaces. */
export function validateLockReason(value: string) {
  const normalized = value.replace(/[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/g, " ").replace(/^ | $/g, "");
  const length = Array.from(normalized).length;
  const plain = !/[\u0000-\u001f\u007f]/.test(normalized);
  const valid = plain && length >= 8 && length <= 500;
  const hint = !plain
    ? "Use plain text without control characters."
    : length < 8
      ? `Explain why in 8–500 characters. ${length}/8 characters; add at least ${8 - length} more. Repeated spaces count as one.`
      : length > 500
        ? `Keep the explanation within 500 characters. ${length}/500 characters; remove at least ${length - 500}.`
        : `${length}/500 characters. Leading and trailing spaces are ignored; repeated spaces count as one.`;
  return { normalized, length, valid, commentValid: plain && length <= 500, hint };
}
