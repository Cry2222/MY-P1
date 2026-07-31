/**
 * The trading loop.
 *
 * The only place the components meet. It owns no strategy logic, no risk rules
 * and no venue detail — it moves data across the seams in a fixed order:
 *
 *   market data -> strategy -> position diff -> risk -> execution -> journal -> listeners
 *
 * Risk sits between the strategy and the venue so no signal reaches a venue
 * unchecked, and the journal is written before listeners are notified so a
 * process death cannot lose a fill that already happened.
 */

import type { EngineSettings } from './config';
import { Journal, today } from './journal';
import type { MarketDataSource } from './marketdata';
import { createMarketData } from './marketdata';
import type { Candle, Exposure, Fill, Order, Position, Signal } from './models';
import { newClientId } from './models';
import { RiskEngine, type RiskState } from './risk';
import { EmaCrossStrategy, type Strategy } from './strategy';
import { ExecutionError, PaperVenue } from './venue';

const KILL_KEY = 'kill_switch';
const PAUSE_KEY = 'paused';

export interface EngineStatus {
  running: boolean;
  killed: boolean;
  paused: boolean;
  mode: 'paper';
  venue: string;
  exchange: string;
  symbol: string;
  timeframe: string;
  strategy: string;
  ticks: number;
  errors: number;
  startedAt: number;
  lastTickAt: number;
  lastPrice: number;
  positionSide: Exposure;
  positionQty: number;
  avgPrice: number;
  unrealized: number;
  realizedToday: number;
  realizedTotal: number;
  ordersToday: number;
  equity: number;
  lastError: string;
}

export interface TickResult {
  signal?: Signal;
  order?: Order;
  fill?: Fill;
  rejected?: string;
  note?: string;
}

type Listener = () => void;

export class TradingEngine {
  private marketData: MarketDataSource;
  private strategy: Strategy;
  private risk: RiskEngine;
  private venue: PaperVenue;
  private position!: Position;

  private timer: ReturnType<typeof setTimeout> | null = null;
  private running = false;
  private killed = false;
  private paused = false;
  private ticking = false;

  private ticks = 0;
  private errors = 0;
  private consecutiveErrors = 0;
  private startedAt = 0;
  private lastTickAt = 0;
  private lastPrice = 0;
  private lastError = '';
  private equityCache = 0;
  private realizedToday = 0;
  private realizedTotal = 0;
  private ordersToday = 0;

  private listeners = new Set<Listener>();

  private constructor(
    private settings: EngineSettings,
    private readonly journal: Journal,
  ) {
    this.marketData = createMarketData(settings.exchange);
    this.strategy = new EmaCrossStrategy(settings.fastPeriod, settings.slowPeriod);
    this.risk = new RiskEngine(settings.risk);
    this.venue = new PaperVenue(settings.startingCash, settings.feePct, settings.slippagePct);
  }

  static async create(settings: EngineSettings, journal: Journal): Promise<TradingEngine> {
    const engine = new TradingEngine(settings, journal);
    await engine.restore();
    return engine;
  }

  /**
   * Rebuild live state from the journal.
   *
   * Called on every start, because on Android "the app was killed" is a normal
   * event rather than a crash. Coming back up must re-read reality, never
   * assume a flat book.
   */
  private async restore(): Promise<void> {
    this.position = await this.journal.rebuildPosition(this.settings.symbol);
    const cash = await this.journal.rebuildCash(this.settings.startingCash);
    this.venue.seed(this.settings.symbol, this.position.quantity, cash);

    this.killed = await this.journal.getControl(KILL_KEY, false);
    this.paused = await this.journal.getControl(PAUSE_KEY, false);
    this.realizedToday = await this.journal.realizedPnl(today());
    this.realizedTotal = await this.journal.realizedPnl();
    this.ordersToday = await this.journal.orderCount(today());
    this.equityCache = this.venue.equity(this.lastPrice || this.position.avgPrice || 0);
  }

  // -- listeners -------------------------------------------------------

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(): void {
    for (const l of this.listeners) {
      try {
        l();
      } catch {
        // A broken listener must never stop the trading loop.
      }
    }
  }

  // -- control ---------------------------------------------------------

  get isRunning(): boolean {
    return this.running;
  }

  async start(): Promise<void> {
    if (this.running) return;
    this.running = true;
    this.startedAt = Date.now();
    this.consecutiveErrors = 0;
    await this.journal.log('info', `engine started — ${this.settings.symbol} ${this.settings.timeframe}`);
    this.emit();
    void this.loop();
  }

  async stop(): Promise<void> {
    this.running = false;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    await this.journal.log('info', 'engine stopped');
    this.emit();
  }

  async kill(reason = 'manual'): Promise<void> {
    this.killed = true;
    await this.journal.setControl(KILL_KEY, true);
    await this.journal.log('warn', `KILL SWITCH ENGAGED (${reason})`);
    this.emit();
  }

  async revive(): Promise<void> {
    this.killed = false;
    await this.journal.setControl(KILL_KEY, false);
    await this.journal.log('info', 'kill switch released');
    this.emit();
  }

  async pause(): Promise<void> {
    this.paused = true;
    await this.journal.setControl(PAUSE_KEY, true);
    this.emit();
  }

  async resume(): Promise<void> {
    this.paused = false;
    await this.journal.setControl(PAUSE_KEY, false);
    this.emit();
  }

  /** Apply new settings. Stops the loop; the caller restarts it. */
  async applySettings(next: EngineSettings): Promise<void> {
    const wasRunning = this.running;
    await this.stop();
    this.settings = next;
    this.marketData = createMarketData(next.exchange);
    this.strategy = new EmaCrossStrategy(next.fastPeriod, next.slowPeriod);
    this.risk = new RiskEngine(next.risk);
    this.venue = new PaperVenue(next.startingCash, next.feePct, next.slippagePct);
    await this.restore();
    if (wasRunning) await this.start();
    this.emit();
  }

  async resetHistory(): Promise<void> {
    const wasRunning = this.running;
    await this.stop();
    await this.journal.reset();
    this.ticks = 0;
    this.errors = 0;
    this.lastError = '';
    await this.restore();
    if (wasRunning) await this.start();
    this.emit();
  }

  // -- the loop --------------------------------------------------------

  private async loop(): Promise<void> {
    while (this.running) {
      try {
        await this.tick();
      } catch (error) {
        this.errors += 1;
        this.consecutiveErrors += 1;
        this.lastError = error instanceof Error ? error.message : String(error);
        await this.journal.log('error', `tick failed: ${this.lastError}`);
        if (this.consecutiveErrors >= 10) {
          await this.kill('too many consecutive errors');
          await this.stop();
          break;
        }
      }
      this.emit();
      if (!this.running) break;
      await this.sleep(this.settings.pollSeconds * 1000);
    }
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => {
      this.timer = setTimeout(resolve, ms);
    });
  }

  /** Run exactly one pass of the pipeline. Exposed for tests. */
  async tick(): Promise<TickResult> {
    if (this.ticking) return { note: 'already ticking' };
    this.ticking = true;
    try {
      this.ticks += 1;
      this.lastTickAt = Date.now();

      const candles = await this.marketData.fetchCandles(
        this.settings.symbol,
        this.settings.timeframe,
        Math.max(this.strategy.warmup + 50, 100),
      );
      if (candles.length === 0) return { note: 'no candles' };

      this.lastPrice = candles[candles.length - 1].close;
      this.equityCache = this.venue.equity(this.lastPrice);
      this.consecutiveErrors = 0;
      this.lastError = '';

      const signal = this.strategy.evaluate(candles);
      if (!signal) return { note: 'strategy abstained' };

      const planned = this.plan(signal);
      if (!planned) return { signal, note: 'target already held' };
      const { order, isExit } = planned;

      const state = await this.riskState(candles[candles.length - 1]);
      const decision = this.risk.assess(signal, this.position, state, isExit);
      if (!decision.approved) {
        await this.journal.recordOrder(order, 'rejected', decision.reason);
        return { signal, order, rejected: decision.reason };
      }

      const sized: Order = { ...order, quantity: decision.quantity };

      let fill: Fill;
      try {
        fill = await this.venue.submit(sized);
      } catch (error) {
        const message = error instanceof ExecutionError ? error.message : String(error);
        this.errors += 1;
        await this.journal.recordOrder(sized, 'failed', message);
        await this.journal.log('error', `execution failed: ${message}`);
        return { signal, order: sized, rejected: message };
      }

      await this.commit(fill, sized);
      return { signal, order: sized, fill };
    } finally {
      this.ticking = false;
    }
  }

  /** Derive the order that moves the live position to the signal's target. */
  private plan(signal: Signal): { order: Order; isExit: boolean } | null {
    const current = this.position.exposure;
    if (current === signal.target) return null;

    const clientId = newClientId();

    // Leaving an open position always takes priority over entering a new one.
    // A reversal is executed as an exit now and an entry next tick, so a single
    // order never crosses through zero.
    if (!this.position.isFlat) {
      return {
        order: {
          symbol: this.settings.symbol,
          side: current === 'long' ? 'sell' : 'buy',
          quantity: Math.abs(this.position.quantity),
          price: signal.price,
          reason: `exit ${current}: ${signal.reason}`,
          clientId,
        },
        isExit: true,
      };
    }

    if (signal.target === 'flat') return null;

    return {
      order: {
        symbol: this.settings.symbol,
        side: signal.target === 'long' ? 'buy' : 'sell',
        quantity: 0, // the risk engine sets the real size
        price: signal.price,
        reason: `enter ${signal.target}: ${signal.reason}`,
        clientId,
      },
      isExit: false,
    };
  }

  private async riskState(candle: Candle): Promise<RiskState> {
    return {
      equity: this.venue.equity(candle.close),
      realizedPnlToday: await this.journal.realizedPnl(today()),
      ordersToday: await this.journal.orderCount(today()),
      killed: this.killed,
      paused: this.paused,
    };
  }

  private async commit(fill: Fill, order: Order): Promise<void> {
    const realized = this.position.apply(fill);
    await this.journal.recordFill(fill, realized);
    await this.journal.recordOrder(order, 'filled', `realized ${realized.toFixed(4)}`);
    await this.journal.log(
      'info',
      `${fill.side.toUpperCase()} ${fill.quantity.toFixed(8)} @ ${fill.price.toFixed(4)} → ${realized >= 0 ? '+' : ''}${realized.toFixed(4)}`,
    );

    this.realizedToday = await this.journal.realizedPnl(today());
    this.realizedTotal = await this.journal.realizedPnl();
    this.ordersToday = await this.journal.orderCount(today());
    this.equityCache = this.venue.equity(this.lastPrice);
  }

  // -- reporting -------------------------------------------------------

  status(): EngineStatus {
    return {
      running: this.running,
      killed: this.killed,
      paused: this.paused,
      mode: 'paper',
      venue: this.venue.name,
      exchange: this.settings.exchange,
      symbol: this.settings.symbol,
      timeframe: this.settings.timeframe,
      strategy: this.strategy.name,
      ticks: this.ticks,
      errors: this.errors,
      startedAt: this.startedAt,
      lastTickAt: this.lastTickAt,
      lastPrice: this.lastPrice,
      positionSide: this.position.exposure,
      positionQty: this.position.quantity,
      avgPrice: this.position.avgPrice,
      unrealized: this.position.unrealizedPnl(this.lastPrice),
      realizedToday: this.realizedToday,
      realizedTotal: this.realizedTotal,
      ordersToday: this.ordersToday,
      equity: this.equityCache,
      lastError: this.lastError,
    };
  }

  getSettings(): EngineSettings {
    return this.settings;
  }

  getJournal(): Journal {
    return this.journal;
  }

  async candles(limit = 90): Promise<Candle[]> {
    return this.marketData.fetchCandles(this.settings.symbol, this.settings.timeframe, limit);
  }
}
