"""
bot/display.py — Terminal Dashboard for Crypto Volatility Bot
"""
import os
import time
from colorama import Fore, Back, Style, init
from tabulate import tabulate
from bot.risk import RiskManager
from bot.analytics import classify_vpin

init(autoreset=True)
LINE = "─" * 72


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def clr(text, color):
    return f"{color}{text}{Style.RESET_ALL}"


def pnl_str(val: float) -> str:
    if val > 0:   return clr(f"+${val:.4f}", Fore.GREEN)
    elif val < 0: return clr(f"-${abs(val):.4f}", Fore.RED)
    return clr(f"${val:.4f}", Fore.WHITE)


def mom_str(val: float) -> str:
    arrow = "UP" if val > 0 else ("DN" if val < 0 else "--")
    color = Fore.GREEN if val > 0 else (Fore.RED if val < 0 else Fore.WHITE)
    return clr(f"{arrow} {val:+.4%}", color)


def signal_icon(passed: bool) -> str:
    return clr("[Y]", Fore.GREEN) if passed else clr("[N]", Fore.RED)


def render_header(dry_run: bool, cycle: int):
    mode = clr(" DRY RUN ", Back.YELLOW + Fore.BLACK) if dry_run \
           else clr(" LIVE TRADING ", Back.RED + Fore.WHITE)
    title = clr("POLYMARKET CRYPTO VOLATILITY BOT", Fore.CYAN + Style.BRIGHT)
    print(f"\n{title}  {mode}")
    print(clr(f"  BTC / ETH / SOL  |  Cycle #{cycle}  |  {time.strftime('%H:%M:%S')}", Style.DIM))
    print(clr(LINE, Fore.CYAN))


def render_price_panel(feed_summary: dict):
    print(f"\n{clr('LIVE SPOT PRICES', Fore.YELLOW + Style.BRIGHT)}")
    print(clr(LINE, Fore.YELLOW))
    rows = []
    for symbol, data in feed_summary.items():
        price = data.get("price", 0)
        s_mom = data.get("short_momentum", 0)
        m_mom = data.get("medium_momentum", 0)
        vol   = data.get("volatility", 0)
        n     = data.get("samples", 0)
        trend = "BULLISH" if s_mom > 0.001 else ("BEARISH" if s_mom < -0.001 else "NEUTRAL")
        tcol  = Fore.GREEN if "BULL" in trend else (Fore.RED if "BEAR" in trend else Fore.WHITE)
        rows.append([
            clr(symbol, Fore.CYAN + Style.BRIGHT),
            f"${price:,.2f}",
            mom_str(s_mom),
            mom_str(m_mom),
            f"{vol:.4%}",
            clr(trend, tcol),
            f"{n} pts",
        ])
    print(tabulate(rows,
        headers=["Asset", "Price", "Short Mom", "Med Mom", "Volatility", "Trend", "Samples"],
        tablefmt="simple"))


def render_opportunities(opportunities: list):
    if not opportunities:
        print(f"\n{clr('No opportunities found this cycle.', Style.DIM)}")
        return
    print(f"\n{clr('TOP OPPORTUNITIES', Fore.MAGENTA + Style.BRIGHT)}")
    print(clr(LINE, Fore.MAGENTA))
    rows = []
    for opp in opportunities[:8]:
        asset    = clr(opp["asset"], Fore.CYAN + Style.BRIGHT)
        yes_p    = opp["yes_price"]
        mtype    = opp["market_type"].replace("_", " ")
        tf       = opp["timeframe"]
        vol      = opp["volume_24h"]
        question = opp["question"][:38] + "..." if len(opp["question"]) > 38 else opp["question"]
        score    = opp["score"]
        uncert   = 1.0 - abs(yes_p - 0.5) * 2
        bar_len  = int(uncert * 8)
        bar      = ("#" * bar_len).ljust(8)
        bar_col  = Fore.GREEN if uncert > 0.7 else (Fore.YELLOW if uncert > 0.4 else Fore.RED)
        rows.append([
            asset, tf, mtype,
            f"{yes_p:.3f}",
            clr(bar, bar_col),
            f"${vol:,.0f}",
            f"{score:.3f}",
            question,
        ])
    print(tabulate(rows,
        headers=["Asset", "TF", "Type", "YES", "Uncert", "Vol 24h", "Score", "Market"],
        tablefmt="simple"))


def render_positions(risk: RiskManager):
    print(f"\n{clr('ACTIVE POSITIONS', Fore.CYAN + Style.BRIGHT)}")
    print(clr(LINE, Fore.CYAN))
    if not risk.positions:
        print(clr("  No open positions.", Style.DIM))
        return
    rows = []
    for tid, pos in risk.positions.items():
        rows.append([
            pos.market_name[:45],
            f"${pos.buy_price:.4f}",
            f"${pos.size_usdc:.2f}",
            pnl_str(pos.realized_pnl),
        ])
    print(tabulate(rows, headers=["Market", "Entry", "Size", "PnL"], tablefmt="simple"))


def render_risk_panel(risk: RiskManager):
    s = risk.summary()
    halted, reason = risk.is_halted()
    status = clr(f"HALTED: {reason}", Fore.RED + Style.BRIGHT) if halted \
             else clr("RUNNING", Fore.GREEN + Style.BRIGHT)
    print(f"\n{clr('RISK & PERFORMANCE', Fore.YELLOW + Style.BRIGHT)}")
    print(clr(LINE, Fore.YELLOW))
    print(f"  Status      : {status}")
    print(f"  Session PnL : {pnl_str(s['daily_pnl'])}")
    print(f"  Trades      : {s['total_trades']}  |  "
          f"Win Rate: {clr(str(round(s['win_rate'], 1)) + '%', Fore.GREEN if s['win_rate'] >= 50 else Fore.RED)}")
    print(f"  Exposure    : ${s['total_exposure']:.2f}  |  Active: {s['active_markets']}  |  "
          f"Duration: {s['session_duration']}")


def render_microstructure(vpin: float, roll: float):
    zone, advice = classify_vpin(vpin)
    zcol = {"LOW": Fore.GREEN, "MODERATE": Fore.YELLOW,
            "ELEVATED": Fore.LIGHTYELLOW_EX, "TOXIC": Fore.RED}.get(zone, Fore.WHITE)
    print(f"\n{clr('MICROSTRUCTURE', Fore.BLUE + Style.BRIGHT)}")
    print(clr(LINE, Fore.BLUE))
    print(f"  VPIN  : {clr(f'{vpin:.3f} [{zone}]', zcol)}  --  {advice}")
    roll_note = "High momentum" if roll > 0.025 else "Stable"
    print(f"  Roll  : {clr(f'{roll:.4f}', Fore.CYAN)}  --  {roll_note}")


def render_signals(signals: list):
    if not signals:
        return
    print(f"\n{clr('SIGNAL GATE', Fore.WHITE + Style.BRIGHT)}")
    print(clr(LINE, Fore.WHITE))
    for s in signals:
        icon = signal_icon(s["pass"])
        print(f"  {icon}  {s['name']:<18}  {s['value']:<14}  "
              f"(need: {s['threshold']:<22})  {clr(s['weight'], Style.DIM)}")


def render_log(events: list, n: int = 14):
    if not events:
        return
    print(f"\n{clr('ACTIVITY LOG', Fore.WHITE + Style.BRIGHT)}")
    print(clr(LINE, Fore.WHITE))
    colors = {"INFO": Fore.WHITE, "SUCCESS": Fore.GREEN,
              "WARN": Fore.YELLOW, "ERROR": Fore.RED, "DEBUG": Style.DIM}
    for e in events[-n:]:
        col = colors.get(e["level"], Fore.WHITE)
        print(f"  {clr(e['ts'], Style.DIM)}  {clr('[' + e['level'] + ']', col):<20}  {e['msg']}")


def render_footer(interval: int):
    print(f"\n{clr(LINE, Fore.CYAN)}")
    print(clr(f"  Refreshing every {interval}s  |  Ctrl+C to stop  |  --dry-run to test safely\n",
              Style.DIM))


def render_dashboard(risk, strategy, feed_summary, dry_run, refresh_interval=60):
    clear()
    render_header(dry_run, strategy.cycle)
    render_price_panel(feed_summary)
    render_opportunities(strategy.opportunities)
    render_positions(risk)
    render_risk_panel(risk)
    render_microstructure(strategy.last_vpin, strategy.last_roll)
    if strategy.last_signals:
        render_signals(strategy.last_signals)
    render_log(strategy.events)
    render_footer(refresh_interval)
