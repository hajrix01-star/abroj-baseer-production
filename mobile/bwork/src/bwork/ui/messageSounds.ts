import AsyncStorage from '@react-native-async-storage/async-storage';
import { AppState, NativeModules } from 'react-native';
import type { Bootstrap, Message, Room } from '../core/ChatEngine';
import { config } from '../runtime';

export type SoundKind = 'send' | 'receive';
export type SoundState = { actor: string; ready: boolean; enabled: boolean };
type SoundPorts = {
  load: (key: string) => Promise<string | null>;
  save: (key: string, value: string) => Promise<unknown>;
  play: (kind: SoundKind) => void;
  stop: () => void;
};
const voiceOwners = new Set<object>();
export function stopFeedback() {
  try {
    NativeModules?.BWorkFeedback?.stop();
  } catch {
    /* Optional feedback never blocks work. */
  }
}
export function setFeedbackVoice(owner: object, active: boolean) {
  if (active) {
    voiceOwners.add(owner);
    stopFeedback();
  } else voiceOwners.delete(owner);
}
function playFeedback(kind: SoundKind) {
  if (AppState.currentState !== 'active' || voiceOwners.size) return;
  try {
    void NativeModules?.BWorkFeedback?.play(kind)?.catch(() => undefined);
  } catch {
    /* Feedback must never fail a message operation. */
  }
}
export function soundActor(identity: Bootstrap | null): string {
  return identity?.permissions.chat_view === true
    ? JSON.stringify([config.origin, identity.database, identity.user_id])
    : '';
}
export function soundRoom(actor: string, room: Room | null): string {
  return actor && room ? JSON.stringify([actor, room.company_id, room.id, room.membership_id]) : '';
}

/** One open-room watermark, not a second history cache or background receiver. */
export class MessageSounds {
  private state: SoundState = { actor: '', ready: false, enabled: false };
  private epoch = 0;
  private room = '';
  private high = 0;
  private initialized = false;
  private saves: Promise<unknown> = Promise.resolve();
  constructor(
    private ports: SoundPorts,
    private changed: (state: SoundState) => void,
  ) {}
  snapshot(): SoundState {
    return { ...this.state };
  }
  account(actor: string) {
    if (actor === this.state.actor) return;
    const epoch = ++this.epoch;
    this.reset();
    this.state = { actor, ready: false, enabled: false };
    this.changed(this.snapshot());
    if (!actor) return;
    void this.ports
      .load(this.key(actor))
      .then(value => {
        if (epoch !== this.epoch || actor !== this.state.actor) return;
        this.state = { actor, ready: true, enabled: value === null || value === '1' };
        this.changed(this.snapshot());
      })
      .catch(() => {
        if (epoch !== this.epoch || actor !== this.state.actor) return;
        this.state = { actor, ready: true, enabled: false };
        this.changed(this.snapshot());
      });
  }
  private key(actor: string) {
    return `bwork/chat-sounds/v1/${encodeURIComponent(actor)}`;
  }
  enabled(value: boolean) {
    if (!this.state.actor || !this.state.ready) return;
    const actor = this.state.actor;
    const epoch = this.epoch;
    this.state = { ...this.state, enabled: value };
    this.changed(this.snapshot());
    if (!value) this.ports.stop();
    this.saves = this.saves
      .catch(() => undefined)
      .then(async () => {
        if (this.epoch === epoch && this.state.actor === actor)
          await this.ports.save(this.key(actor), value ? '1' : '0');
      })
      .catch(() => undefined);
  }
  reset() {
    this.room = '';
    this.high = 0;
    this.initialized = false;
    this.ports.stop();
  }
  observe(room: string, messages: readonly Message[], uid: number, baseline = false) {
    const high = messages.reduce((max, message) => Math.max(max, message.id), 0);
    const fresh =
      !baseline &&
      this.initialized &&
      room === this.room &&
      messages.some(message => message.id > this.high && message.author_user_id !== uid);
    this.high = room === this.room && !baseline ? Math.max(this.high, high) : high;
    this.room = room;
    this.initialized = !!room;
    if (fresh && this.state.ready && this.state.enabled) this.ports.play('receive');
  }
  sent(room: string) {
    if (room && room === this.room && this.state.ready && this.state.enabled)
      this.ports.play('send');
  }
  close() {
    this.epoch++;
    this.state = { actor: '', ready: false, enabled: false };
    this.reset();
  }
}
export function createMessageSounds(changed: (state: SoundState) => void) {
  return new MessageSounds(
    {
      load: key => AsyncStorage.getItem(key),
      save: (key, value) => AsyncStorage.setItem(key, value),
      play: playFeedback,
      stop: stopFeedback,
    },
    changed,
  );
}
