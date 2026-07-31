"""Telegram control surface.

The gateway is a view onto the runner and a remote for its control state. It
holds no trading logic of its own: every command it exposes maps to a method
the runner already has, so the bot behaves identically whether it is driven
from Telegram or from a test.

Authorisation is a single allowlisted chat id. Commands from anyone else are
logged and dropped — this bot can spend money, so an open command surface is
not an option.
"""

from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from ..config import TelegramConfig

if TYPE_CHECKING:
    from ..runner import TradingRunner

log = logging.getLogger(__name__)

HELP = """<b>MY-P1 trading bot</b>

/status — mode, position, PnL, uptime
/position — open position detail
/pnl — realized and unrealized PnL
/fills — last 10 fills
/pause — stop opening new positions
/resume — allow new positions again
/kill — <b>halt everything</b>, including exits
/revive — release the kill switch
/help — this message"""


class TelegramGateway:
    def __init__(self, config: TelegramConfig, runner: TradingRunner) -> None:
        if not config.usable:
            raise ValueError("TelegramGateway requires a token and an owner chat id")
        self.config = config
        self.runner = runner
        self.app: Application = Application.builder().token(config.token).build()
        self._register()

    def _register(self) -> None:
        handlers = {
            "start": self.cmd_status,
            "status": self.cmd_status,
            "position": self.cmd_position,
            "pnl": self.cmd_pnl,
            "fills": self.cmd_fills,
            "pause": self.cmd_pause,
            "resume": self.cmd_resume,
            "kill": self.cmd_kill,
            "revive": self.cmd_revive,
            "help": self.cmd_help,
        }
        for name, handler in handlers.items():
            self.app.add_handler(CommandHandler(name, handler))

    # -- authorisation --------------------------------------------------

    def _authorised(self, update: Update) -> bool:
        chat = update.effective_chat
        if chat is None or chat.id != self.config.owner_chat_id:
            log.warning(
                "dropped command from unauthorised chat %s",
                chat.id if chat else "unknown",
            )
            return False
        return True

    async def _reply(self, update: Update, text: str) -> None:
        if update.effective_message is not None:
            await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)

    # -- commands -------------------------------------------------------

    async def cmd_help(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorised(update):
            return
        await self._reply(update, HELP)

    async def cmd_status(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorised(update):
            return
        s = self.runner.status()
        flags = []
        if s["killed"]:
            flags.append("🛑 KILLED")
        if s["paused"]:
            flags.append("⏸ paused")
        if not flags:
            flags.append("✅ active")

        badge = "🔴 LIVE" if s["mode"] == "live" else "📄 paper"
        await self._reply(update, (
            f"<b>MY-P1</b> {badge} · {' '.join(flags)}\n\n"
            f"<b>Market</b> {html.escape(s['symbol'])} {s['timeframe']}\n"
            f"<b>Strategy</b> {html.escape(s['strategy'])}\n"
            f"<b>Venue</b> {html.escape(s['venue'])}\n"
            f"<b>Last price</b> {s['last_price']:.4f}\n\n"
            f"<b>Position</b> {s['position_side']} {s['position_qty']:.8f}\n"
            f"<b>Avg price</b> {s['avg_price']:.4f}\n"
            f"<b>Unrealized</b> {s['unrealized']:+.4f}\n"
            f"<b>Realized today</b> {s['realized_today']:+.4f}\n\n"
            f"<b>Ticks</b> {s['ticks']} · <b>errors</b> {s['errors']}\n"
            f"<b>Orders today</b> {s['orders_today']}\n"
            f"<b>Uptime</b> {s['uptime_seconds']:.0f}s"
        ))

    async def cmd_position(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorised(update):
            return
        p = self.runner.position
        if p.is_flat:
            await self._reply(update, "No open position.")
            return
        mark = self.runner.last_price
        await self._reply(update, (
            f"<b>{html.escape(p.symbol)}</b> {p.exposure.value}\n"
            f"Quantity {p.quantity:.8f}\n"
            f"Avg price {p.avg_price:.4f}\n"
            f"Mark {mark:.4f}\n"
            f"Unrealized {p.unrealized_pnl(mark):+.4f}"
        ))

    async def cmd_pnl(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorised(update):
            return
        s = self.runner.status()
        await self._reply(update, (
            f"<b>PnL</b>\n"
            f"Realized today {s['realized_today']:+.4f}\n"
            f"Realized total {s['realized_total']:+.4f}\n"
            f"Unrealized {s['unrealized']:+.4f}\n"
            f"Net {s['realized_total'] + s['unrealized']:+.4f}"
        ))

    async def cmd_fills(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorised(update):
            return
        rows = self.runner.journal.recent_fills(limit=10)
        if not rows:
            await self._reply(update, "No fills yet.")
            return
        lines = [
            f"{r['side'].upper():4} {r['quantity']:.6f} @ {r['price']:.4f} "
            f"→ {r['realized']:+.4f}"
            for r in rows
        ]
        await self._reply(update, "<b>Recent fills</b>\n<pre>" +
                          html.escape("\n".join(lines)) + "</pre>")

    async def cmd_pause(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorised(update):
            return
        self.runner.pause()
        await self._reply(update, "⏸ Paused. Open positions can still exit. /resume to restart.")

    async def cmd_resume(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorised(update):
            return
        if self.runner.killed:
            await self._reply(update, "🛑 Kill switch is engaged. Use /revive first.")
            return
        self.runner.resume()
        await self._reply(update, "▶️ Resumed.")

    async def cmd_kill(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorised(update):
            return
        self.runner.kill("telegram")
        await self._reply(update, (
            "🛑 <b>Kill switch engaged.</b>\n"
            "No orders will be placed — including exits. Any open position is "
            "now yours to close by hand on the exchange.\n"
            "/revive to release."
        ))

    async def cmd_revive(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorised(update):
            return
        self.runner.revive()
        await self._reply(update, "Kill switch released. Still paused? use /resume.")

    # -- outbound -------------------------------------------------------

    async def send(self, text: str) -> None:
        """Notifier callback handed to the runner."""
        await self.app.bot.send_message(chat_id=self.config.owner_chat_id, text=text)

    # -- lifecycle ------------------------------------------------------

    async def start(self) -> None:
        await self.app.initialize()
        await self.app.start()
        if self.app.updater is not None:
            await self.app.updater.start_polling(drop_pending_updates=True)
        log.info("telegram gateway polling")

    async def stop(self) -> None:
        if self.app.updater is not None:
            await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()
        log.info("telegram gateway stopped")
