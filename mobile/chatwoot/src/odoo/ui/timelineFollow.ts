/** Presentation-only policy. Never acknowledges a message or changes queue state. */
export const NEAR_BOTTOM_DP = 64;

export class TimelineFollow {
  following = true;
  private lastKey: string | undefined;

  scroll(contentHeight: number, viewportHeight: number, offset: number) {
    this.following = contentHeight - viewportHeight - Math.max(0, offset) <= NEAR_BOTTOM_DP;
    return this.following;
  }

  /** A prepend leaves the last key unchanged; a receipt edit does too. */
  rows(lastKey: string | undefined) {
    const changed = lastKey !== this.lastKey;
    this.lastKey = lastKey;
    return changed && this.following;
  }

  ownEnqueued() {
    this.following = true;
  }
}
