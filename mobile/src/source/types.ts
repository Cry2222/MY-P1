/**
 * Bot source seam.
 *
 * The dashboard reads through this and does not know whether the bot is the
 * engine running inside this app or a Python bot on a server. Same rule the
 * Python side applies to its own components: the screen depends on a shape,
 * not on an implementation.
 */

import type { Candle } from '../engine/models';
import type { EngineStatus } from '../engine/runner';

export type SourceKind = 'local' | 'remote';

export interface FillView {
  id: number;
  side: 'buy' | 'sell';
  quantity: number;
  price: number;
  realized: number;
  timestamp: number;
}

export interface BotSource {
  readonly kind: SourceKind;
  /** Human label for the header, e.g. "This phone" or the server address. */
  readonly label: string;

  status(): Promise<EngineStatus>;
  fills(limit?: number): Promise<FillView[]>;
  candles(limit?: number): Promise<Candle[]>;

  pause(): Promise<void>;
  resume(): Promise<void>;
  kill(): Promise<void>;
  revive(): Promise<void>;

  /** Only meaningful for a local engine; remote bots run themselves. */
  start?(): Promise<void>;
  stop?(): Promise<void>;

  /** Called when a change should refresh the UI. Returns an unsubscribe fn. */
  subscribe?(listener: () => void): () => void;
}
