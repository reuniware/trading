"""
Dashboard Streamlit pour le système de trading ICT.
Affichage temps réel des données MT5, signaux, positions, et KPIs.
"""

import time
import logging
from typing import Dict, Optional
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import sys
sys.path.insert(0, '.')
from src.config import TIMEFRAME_HIERARCHY, TIMEFRAME_LABELS, TIMEFRAME_BARS, TIMEFRAME_NAMES
from src.mt5_connector import MT5Connector
from src.data_engine import DataEngine
from src.ict_concepts import ICTConceptsDetector
from src.sessions import SessionDetector
from src.signal_generator import SignalGenerator
from src.trade_manager import TradeManager
from src.risk_manager import RiskManager
from src.account_monitor import AccountMonitor
from src.analyzer import ICTAnalyzer

logger = logging.getLogger("Dashboard")

# Configuration de la page
st.set_page_config(
    page_title="ICT Trading System — FTMO",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── CSS personnalisé ──────────────────────────────────────────────────────

CUSTOM_CSS = """
<style>
    /* Thème dark */
    .stApp { background-color: #0E1117; }
    
    /* Cards métriques */
    .metric-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid #2a2a4a;
        border-radius: 12px;
        padding: 16px 20px;
        margin: 8px 0;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    .metric-card .label {
        font-size: 0.8rem;
        color: #888;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .metric-card .value {
        font-size: 1.5rem;
        font-weight: 700;
        margin-top: 4px;
    }
    .metric-card .value.positive { color: #00ff88; }
    .metric-card .value.negative { color: #ff4444; }
    .metric-card .value.neutral { color: #ffaa00; }
    
    /* Signal cards */
    .signal-card {
        background: linear-gradient(135deg, #1a2a1a 0%, #0d1f0d 100%);
        border: 1px solid #2a4a2a;
        border-radius: 12px;
        padding: 16px;
        margin: 8px 0;
    }
    .signal-card.sell {
        background: linear-gradient(135deg, #2a1a1a 0%, #1f0d0d 100%);
        border: 1px solid #4a2a2a;
    }
    
    /* Session badges */
    .session-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
        margin: 2px;
    }
    .session-badge.active {
        background: #00ff8844;
        border: 1px solid #00ff88;
        color: #00ff88;
    }
    .session-badge.inactive {
        background: #444;
        color: #888;
    }
    
    /* Header */
    h1, h2, h3 { color: #e0e0e0 !important; }
    .st-emotion-cache-16idsys p { font-size: 0.9rem; }
</style>
"""


def init_state():
    """Initialise l'état de session Streamlit."""
    if "data_engine" not in st.session_state:
        st.session_state.data_engine = DataEngine()
    if "session_detector" not in st.session_state:
        st.session_state.session_detector = SessionDetector()
    if "signal_gen" not in st.session_state:
        st.session_state.signal_gen = SignalGenerator()
    if "trade_mgr" not in st.session_state:
        st.session_state.trade_mgr = TradeManager()
    if "account" not in st.session_state:
        st.session_state.account = AccountMonitor()
    if "analyzer" not in st.session_state:
        st.session_state.analyzer = ICTAnalyzer()
    if "autorefresh" not in st.session_state:
        st.session_state.autorefresh = True
    if "last_refresh" not in st.session_state:
        st.session_state.last_refresh = time.time()
    if "active_tfs" not in st.session_state:
        st.session_state.active_tfs = list(TIMEFRAME_NAMES)


CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "JPY": "¥", "CHF": "CHF", "CAD": "C$", "AUD": "A$"}

def get_currency_symbol(currency: str) -> str:
    """Retourne le symbole monétaire depuis le code devise."""
    return CURRENCY_SYMBOLS.get(currency.upper(), currency)

def format_money(value: float, currency: str = "USD") -> str:
    """Formate un montant avec la devise correcte."""
    symbol = get_currency_symbol(currency)
    sign = "+" if value >= 0 else ""
    if symbol in ("€", "£", "¥"):
        return f"{sign}{symbol}{value:,.2f}"
    else:
        return f"{sign}{symbol}{value:,.2f}" if symbol == "$" else f"{sign}{value:,.2f} {symbol}"

def format_pnl(value: float) -> str:
    """Formate un PnL avec couleur."""
    color = "#00ff88" if value >= 0 else "#ff4444"
    sign = "+" if value >= 0 else ""
    return f'<span style="color:{color}">{sign}{value:.2f}</span>'


def render_metric(label: str, value: str, color_class: str = "neutral"):
    """Affiche une métrique dans une card."""
    st.markdown(
        f'<div class="metric-card">'
        f'<div class="label">{label}</div>'
        f'<div class="value {color_class}">{value}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_candle_chart(df: pd.DataFrame, symbol: str, tf_label: str, show_ict: bool = True):
    """Graphique bougies avec concepts ICT."""
    if df is None or len(df) < 10:
        st.warning("Pas assez de données pour le graphique")
        return

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.75, 0.25],
    )

    # Bougies
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name=symbol,
            increasing_line_color="#00ff88",
            decreasing_line_color="#ff4444",
        ),
        row=1, col=1,
    )

    # Volume
    colors = ["rgba(0,255,136,0.27)" if df["close"].iloc[i] >= df["open"].iloc[i] else "rgba(255,68,68,0.27)"
              for i in range(len(df))]
    fig.add_trace(
        go.Bar(
            x=df.index,
            y=df["volume"],
            name="Volume",
            marker_color=colors,
            opacity=0.7,
        ),
        row=2, col=1,
    )

    # Concepts ICT (si demandé)
    if show_ict and len(df) > 20:
        detector = ICTConceptsDetector(tf_name="")
        detector.tf = tf_label

        obs = detector.detect_order_blocks(df)
        for ob in obs[-5:]:  # 5 derniers OB
            color = "#00ff88" if ob.type == "bullish" else "#ff4444"
            fig.add_hline(
                y=ob.high, line_color=color, line_dash="dash", opacity=0.4,
                annotation_text=f"OB {ob.type}",
                row=1, col=1,
            )

        fvgs = detector.detect_fvg(df)
        for fvg in fvgs[-5:]:
            color = "rgba(0,255,136,0.15)" if fvg.type == "bullish" else "rgba(255,68,68,0.15)"
            fig.add_hrect(
                y0=fvg.lower, y1=fvg.upper,
                fillcolor=color, line_width=0,
                row=1, col=1,
            )

    # Layout
    fig.update_layout(
        template="plotly_dark",
        height=400,
        margin=dict(l=0, r=0, t=20, b=0),
        xaxis_rangeslider_visible=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#888"),
    )

    fig.update_yaxes(gridcolor="#1a1a2e", row=1, col=1)
    fig.update_yaxes(gridcolor="#1a1a2e", row=2, col=1)

    st.plotly_chart(fig, use_container_width=True)


def render_signal_card(signal, idx: int):
    """Affiche un signal de trading."""
    direction = "LONG" if signal.direction == "buy" else "SHORT"
    card_class = "signal-card" if signal.direction == "buy" else "signal-card sell"
    direction_color = "#00ff88" if signal.direction == "buy" else "#ff4444"
    conf_color = {"high": "#00ff88", "medium": "#ffaa00", "low": "#ff4444"}.get(signal.confidence, "#888")

    st.markdown(
        f'<div class="{card_class}">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;">'
        f'<h3 style="color:{direction_color};margin:0;">{direction} — Score: {signal.score:.0f}/100</h3>'
        f'<span style="color:{conf_color};font-weight:600;">{signal.confidence.upper()}</span>'
        f'</div>'
        f'<p style="margin:8px 0 4px 0;color:#ccc;">{signal.reason[:120]}</p>'
        f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:12px;">'
        f'<div><span style="color:#888;">Entrée</span><br><span style="color:#fff;font-weight:600;">{signal.entry_zone_low:.1f}-{signal.entry_zone_high:.1f}</span></div>'
        f'<div><span style="color:#888;">TP1</span><br><span style="color:#00ff88;font-weight:600;">{signal.target_1:.1f}</span></div>'
        f'<div><span style="color:#888;">TP2</span><br><span style="color:#00ff88;font-weight:600;">{signal.target_2:.1f}</span></div>'
        f'<div><span style="color:#888;">SL</span><br><span style="color:#ff4444;font-weight:600;">{signal.stop_loss:.1f}</span></div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_dashboard():
    """Page principale du dashboard."""
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    init_state()

    # ─── Computations avant sidebar (nécessaires pour les badges) ────
    all_sessions = st.session_state.session_detector.get_all_sessions()
    countdown_str = ""
    for s in all_sessions:
        if s.active and s.time_until_close:
            if s.name == "silver_bullet":
                countdown_str = f"🔥 {s.label} — ferme dans {s.time_until_close}"
            else:
                countdown_str = f"⏳ {s.label} — ferme dans {s.time_until_close}"
            break
    if not countdown_str:
        for s in all_sessions:
            if not s.active and s.time_until_open:
                if s.name != "silver_bullet":
                    countdown_str = f"⏰ {s.label} ouvre dans {s.time_until_open}"
                else:
                    countdown_str = f"🔥 Silver Bullet dans {s.time_until_open}"
                break

    # ─── Sidebar ───────────────────────────────────────────────────────
    with st.sidebar:
        st.title("📊 ICT Trading System")
        st.caption("Connecté à FTMO Global Markets MT5")

        st.divider()

        # Contrôles
        st.subheader("⚙️ Contrôles")
        symbol = st.selectbox("Symbole", ["XAUUSD", "BTCUSD", "EURUSD", "GBPUSD", "US30"], index=0)
        tf_chart = st.selectbox(
            "Timeframe graphique",
            TIMEFRAME_HIERARCHY,
            index=TIMEFRAME_HIERARCHY.index("H1") if "H1" in TIMEFRAME_HIERARCHY else 0,
            format_func=lambda x: TIMEFRAME_LABELS.get(x, x),
        )

        cols = st.columns(2)
        with cols[0]:
            st.session_state.autorefresh = st.toggle("Auto-refresh", value=st.session_state.autorefresh)
        with cols[1]:
            if st.button("🔄 Refresh", use_container_width=True):
                st.session_state.data_engine.clear_cache()
                st.rerun()

        st.divider()
        st.subheader("⏱️ Timeframes actifs")

        # Checkboxes pour chaque TF
        selected_tfs = []
        for tf_name in TIMEFRAME_NAMES:
            label = TIMEFRAME_LABELS.get(tf_name, tf_name)
            checked = st.checkbox(
                f"{label} ({tf_name})",
                value=tf_name in st.session_state.active_tfs,
                key=f"tf_{tf_name}",
            )
            if checked:
                selected_tfs.append(tf_name)

        if not selected_tfs:
            # Empêcher de tout déco — garder au moins le dernier
            selected_tfs = st.session_state.active_tfs

        if selected_tfs != st.session_state.active_tfs:
            st.session_state.active_tfs = selected_tfs
            st.session_state.data_engine.clear_cache()
            st.rerun()

        st.caption(f"{len(selected_tfs)}/{len(TIMEFRAME_NAMES)} actifs")

        st.divider()
        st.subheader("🕐 Sessions")
        # Réutilise all_sessions calculé avant le sidebar
        for s in all_sessions:
            cls = "active" if s.active else "inactive"
            badge_text = s.label
            if s.active and s.time_until_close:
                badge_text += f" ({s.time_until_close})"
            elif not s.active and s.time_until_open:
                badge_text += f" +{s.time_until_open}"
            st.markdown(
                f'<span class="session-badge {cls}">{badge_text}</span>',
                unsafe_allow_html=True,
            )
        if countdown_str:
            st.caption(countdown_str)

        st.divider()
        st.caption("v1.0 — Système ICT Multi-TF")
        st.caption("Dernière mise à jour: " + datetime.now().strftime("%H:%M:%S"))

    # ─── Refresh data ─────────────────────────────────────────────────
    now = time.time()
    active_tfs = st.session_state.active_tfs
    if st.session_state.autorefresh or now - st.session_state.last_refresh > 30:
        st.session_state.analyzer = ICTAnalyzer()
        analysis = st.session_state.analyzer.analyze_symbol(symbol, force_refresh=True, timeframes=active_tfs)
        st.session_state.last_refresh = now
    else:
        analysis = st.session_state.analyzer.analyze_symbol(symbol, timeframes=active_tfs)

    if "error" in analysis:
        st.error(analysis["error"])
        return

    # ─── Row 0: Contexte Macro ICT ───────────────────────────────────
    st.markdown(f'## {symbol} — Prix Temps Réel')

    # Contexte macro ICT
    macro = st.session_state.session_detector.compute_macro_context(
        analysis.get("bias_matrix", {}),
        analysis.get("proximity", {}),
        analysis.get("sessions", {}),
    )
    macro_color = {"bullish": "#00ff88", "bearish": "#ff4444", "neutral": "#ffaa00"}.get(macro["macro_bias"], "#888")

    # Le décompte countdown_str est déjà calculé avant le sidebar
    if countdown_str:
        macro_label_full = f"{macro['macro_label']} — {countdown_str}"
    else:
        macro_label_full = macro["macro_label"]

    st.markdown(
        f'<div style="background:linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);'
        f'border:1px solid {macro_color};border-radius:12px;padding:12px 20px;'
        f'margin-bottom:12px;text-align:center;">'
        f'<span style="font-size:1.1rem;color:{macro_color};font-weight:700;">{macro_label_full}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ─── Row 1: Explications ICT (expandeur) ────────────────────────────
    with st.expander("📖 Guide ICT — Killzones & Macro", expanded=False):
        kz_now = macro.get("active_killzone", "")

        def _kz_row(emoji, name, utc, desc, active_kz):
            """Génère une ligne de tableau killzone avec mise en évidence si active."""
            if name == active_kz:
                return f"| 🟢👉 **{emoji} {name}** | {utc} | **{desc}** |"
            return f"| {emoji} {name} | {utc} | {desc} |"

        def _att_li(name, advice, active_kz):
            """Génère une ligne d'attitude avec highlight si active."""
            if name == active_kz:
                return f"- 🟢👉 **{name} → {advice}** *(actif maintenant)*"
            return f"- **{name}** → {advice}"

        kz_info = [
            ("🌏", "Asie", "22:00–08:00", "Faible volatilité, ranges, pose les niveaux du jour", "Observer, scalping léger, poser les niveaux"),
            ("🇬🇧", "Londres", "07:00–16:00", "Très volatile, trends directionnels, gros volume", "Trader les trends, entrées sur retraits OB/FVG"),
            ("🇺🇸", "New York", "13:00–21:00", "Pic d'activité (chevauchement Londres 13–16h), liquidité chassée", "Attendre la liquidité (BSL/SSL), reversals possibles"),
            ("🔥", "Silver Bullet NY", "13:30–15:00", "Fenêtre la plus précise, mouvements puissants 1.618+ PD Array", "Entrée sur première impulsion, targets 1.272 PD Array"),
        ]

        col_kz, col_macro = st.columns([1, 1])

        with col_kz:
            # Tableau des killzones avec la ligne active en évidence
            kz_rows = "\n".join(_kz_row(*k[:4], kz_now) for k in kz_info)
            st.markdown(f"""**🔫 Kill Zones** — Créneaux horaires à forte activité

| Zone | UTC | Comportement |
|------|-----|--------------|
{kz_rows}
""")

            # Attitude avec la ligne active en évidence
            att_lines = "\n".join(_att_li(k[1], k[4], kz_now) for k in kz_info)
            st.markdown(f"**Attitude par killzone :**\n{att_lines}")

            if kz_now:
                # Message spécifique à la killzone active
                kz_advice_map = {k[1]: k[4] for k in kz_info}
                advice = kz_advice_map.get(kz_now, "Adapte ta stratégie au contexte")
                st.info(f"🟢 **{kz_now} active** — {advice}")

        with col_macro:
            macro_bias = macro.get("macro_bias", "neutral")
            mb_hl = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}.get(macro_bias, "")

            st.markdown(f"""**📊 Macro ICT** — Contexte global du marché

| Macro | Zone | Attitude |
|-------|------|----------|
| {'🟢👉 **HAUSSIÈRE**' if macro_bias == 'bullish' else '🟢 HAUSSIÈRE'} | Discount (bas du range) | Acheter les retraits vers OB/FVG haussiers |
| {'🔴👉 **BAISSIÈRE**' if macro_bias == 'bearish' else '🔴 BAISSIÈRE'} | Premium (haut du range) | Vendre les rallies vers OB/FVG baissiers |
| {'🟡👉 **NEUTRE**' if macro_bias == 'neutral' else '🟡 NEUTRE'} | Équilibre | Prudence, scalping, attendre Discount/Premium |

**Combinaison killzone + macro :**
| Macro | Killzone | Action |
|-------|----------|-------|
| 🟢 Haussière | Londres → | Acheter les retraits |
| 🟢 Haussière | Silver Bullet → | Long sur première impulsion NY |
| 🔴 Baissière | New York → | Vendre les rallies |
| 🟡 Neutre | Asie → | Observation, poser les niveaux |
""")

            if macro_bias != "neutral":
                zone_label = {"discount": "Zone Discount (achat)", "premium": "Zone Premium (vente)", "equilibrium": "l'Équilibre"}.get(macro.get("price_zone", ""), "")
                st.info(f"{mb_hl} **Macro {macro_bias.upper()}** — Prix en {zone_label}. Suis l'attitude recommandée ci-dessus.")

        st.caption("💡 Les killzones indiquent **quand** trader, la macro indique **dans quelle direction**. Les deux combinées = le plan de trading.")

    cols = st.columns([1, 1, 1, 1, 1, 1])
    price = analysis.get("current_price", {})
    account = analysis.get("account")
    currency = account.currency if account else "USD"
    csym = get_currency_symbol(currency)

    with cols[0]:
        render_metric("Bid", f"${price.get('bid', 0):.2f}", "positive")
    with cols[1]:
        render_metric("Ask", f"${price.get('ask', 0):.2f}", "negative")
    with cols[2]:
        spread = price.get('spread', 0)
        spread_color = "positive" if spread < 20 else ("neutral" if spread < 50 else "negative")
        render_metric("Spread", f"{spread:.1f}", spread_color)

    if account:
        with cols[3]:
            pnl = account.profit
            render_metric("P&L Total", format_money(pnl, currency), "positive" if pnl >= 0 else "negative")
        with cols[4]:
            render_metric("Balance", format_money(account.balance, currency), "positive")
        with cols[5]:
            margin_level = account.margin_level
            ml_color = "positive" if margin_level > 200 else ("neutral" if margin_level > 100 else "negative")
            render_metric("Margin Level", f"{margin_level:.0f}%", ml_color)

    # ─── Row 2: Graphique ─────────────────────────────────────────────
    st.divider()
    st.subheader(f"📈 {symbol} — {TIMEFRAME_LABELS.get(tf_chart, tf_chart)}")

    df = st.session_state.data_engine.fetch_rates(symbol, tf_chart, count=100)
    st.session_state._last_df = df  # Cache

    if df is not None:
        render_candle_chart(df, symbol, tf_chart, show_ict=True)
    else:
        st.warning("Chargement des données...")

    # ─── Row 3: Signaux ───────────────────────────────────────────────
    st.divider()
    st.subheader("🚨 Signaux de Trading")

    signals = analysis.get("signals", [])
    if signals:
        tabs = st.tabs([f"{'🟢 LONG' if s.direction == 'buy' else '🔴 SHORT'} (Score: {s.score:.0f})" for s in signals[:3]])
        for i, (tab, signal) in enumerate(zip(tabs, signals[:3])):
            with tab:
                render_signal_card(signal, i)
                cols = st.columns(3)
                with cols[0]:
                    if st.button(f"🟢 Ouvrir LONG", key=f"buy_{i}", use_container_width=True):
                        result = st.session_state.trade_mgr.place_signal_order(signal)
                        if result:
                            st.success(f"✅ Ordre exécuté!")
                        else:
                            st.error("❌ Échec de l'ordre")
                with cols[1]:
                    st.button(f"🔴 Planifier alerte", key=f"alert_{i}", use_container_width=True)
                with cols[2]:
                    if st.button(f"📋 Détails", key=f"detail_{i}", use_container_width=True):
                        st.info(signal.reason)
    else:
        st.info("🔍 Aucun signal de trading pour le moment. Attente de configuration...")

    # ─── Row 4: Positions ouvertes ────────────────────────────────────
    st.divider()
    col_pos, col_perf = st.columns([1, 1])

    with col_pos:
        st.subheader("📋 Positions Ouvertes")
        positions = st.session_state.trade_mgr.get_position_summary()

        if positions["count"] > 0:
            for pos in positions["positions"]:
                direction = "🟢 LONG" if pos["type"] == "buy" else "🔴 SHORT"
                pnl_color = "#00ff88" if pos["profit"] >= 0 else "#ff4444"
                st.markdown(
                    f'<div class="metric-card">'
                    f'<div style="display:flex;justify-content:space-between;">'
                    f'<span>{direction} {pos["symbol"]}</span>'
                    f'<span style="color:{pnl_color};font-weight:600;">{pos["profit"]:+.2f}</span>'
                    f'</div>'
                    f'<div style="display:flex;justify-content:space-between;color:#888;font-size:0.9rem;">'
                    f'<span>Ticket #{pos["ticket"]}</span>'
                    f'<span>{pos["volume"]} lot | Entrée: {pos["price_open"]:.2f}</span>'
                    f'</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                cols = st.columns(2)
                with cols[0]:
                    if st.button(f"❌ Fermer #{pos['ticket']}", key=f"close_{pos['ticket']}", use_container_width=True):
                        if st.session_state.trade_mgr.close_position(pos["ticket"]):
                            st.success("✅ Position fermée")
                            st.rerun()
                with cols[1]:
                    st.button(f"🔄 Set TP/SL", key=f"modify_{pos['ticket']}", use_container_width=True)
        else:
            st.info("Aucune position ouverte")

    with col_perf:
        st.subheader("📊 Performance (30 jours)")
        perf = st.session_state.account.get_performance_summary(days=30)

        if perf["total_trades"] > 0:
            metrics = {
                "Trades": str(perf["total_trades"]),
                "Win Rate": f"{perf['win_rate']:.1f}%",
                "P&L Total": format_money(perf['total_profit'], currency),
                "Profit Factor": f"{perf['profit_factor']:.2f}" if perf['profit_factor'] != float('inf') else "∞",
                "Avg Profit": format_money(perf['avg_profit'], currency),
                "Max Drawdown": format_money(perf['max_loss'], currency),
            }

            cols = st.columns(2)
            for i, (label, value) in enumerate(metrics.items()):
                with cols[i % 2]:
                    render_metric(label, value, "positive" if i < 3 else "neutral")

            # Courbe d'equity 30j
            equity_df = st.session_state.account.get_equity_curve(days=30)
            if equity_df is not None and len(equity_df) > 0:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=equity_df["time"],
                    y=equity_df["pnl"],
                    mode="lines",
                    name="Equity 30j",
                    line=dict(color="#00ff88", width=2),
                    fill="tozeroy",
                    fillcolor="rgba(0,255,136,0.1)",
                ))
                fig.update_layout(
                    template="plotly_dark",
                    height=200,
                    margin=dict(l=0, r=0, t=10, b=0),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    showlegend=False,
                )
                fig.update_yaxes(gridcolor="#1a1a2e")
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Pas encore d'historique de trades")

        # ─── Performance Totale (tous les trades) ─────────────────
        st.divider()
        st.subheader("🏆 Performance Totale")
        perf_all = st.session_state.account.get_performance_summary(days=None)

        if perf_all["total_trades"] > 0:
            metrics_all = {
                "Trades": str(perf_all["total_trades"]),
                "Win Rate": f"{perf_all['win_rate']:.1f}%",
                "P&L Total": format_money(perf_all['total_profit'], currency),
                "Profit Factor": f"{perf_all['profit_factor']:.2f}" if perf_all['profit_factor'] != float('inf') else "∞",
                "Avg Profit": format_money(perf_all['avg_profit'], currency),
                "Max Drawdown": format_money(perf_all['max_loss'], currency),
            }

            cols_all = st.columns(2)
            for i, (label, value) in enumerate(metrics_all.items()):
                with cols_all[i % 2]:
                    render_metric(label, value, "positive" if i < 3 else "neutral")

            # Courbe d'equity totale
            equity_all_df = st.session_state.account.get_equity_curve(days=None)
            if equity_all_df is not None and len(equity_all_df) > 0:
                fig_all = go.Figure()
                fig_all.add_trace(go.Scatter(
                    x=equity_all_df["time"],
                    y=equity_all_df["pnl"],
                    mode="lines",
                    name="Equity Totale",
                    line=dict(color="#ffaa00", width=2),
                    fill="tozeroy",
                    fillcolor="rgba(255,170,0,0.1)",
                ))
                fig_all.update_layout(
                    template="plotly_dark",
                    height=200,
                    margin=dict(l=0, r=0, t=10, b=0),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    showlegend=False,
                )
                fig_all.update_yaxes(gridcolor="#1a1a2e")
                st.plotly_chart(fig_all, use_container_width=True)
        else:
            st.info("Pas encore d'historique de trades")

    # ─── Row 5: Analyse multi-TF ──────────────────────────────────────
    st.divider()
    st.subheader("🔍 Analyse Multi-Timeframes")

    bias_map = analysis.get("bias_matrix", {})
    display_tfs = analysis.get("active_timeframes", TIMEFRAME_HIERARCHY)
    cols = st.columns(len(display_tfs))
    for i, tf_name in enumerate(display_tfs):
        if i < len(cols):
            with cols[i]:
                bias = bias_map.get(tf_name, "neutral")
                label = TIMEFRAME_LABELS.get(tf_name, tf_name)
                icons = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}
                colors = {"bullish": "#00ff88", "bearish": "#ff4444", "neutral": "#ffaa00"}
                st.markdown(
                    f'<div class="metric-card" style="text-align:center;">'
                    f'<div class="label">{label}</div>'
                    f'<div class="value" style="color:{colors.get(bias, "#888")};">{icons.get(bias, "⚪")}</div>'
                    f'<div style="font-size:0.8rem;color:#888;margin-top:4px;">{bias.upper()}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    # Conflits
    if analysis.get("conflicts"):
        st.warning("⚠️ **Conflit de Timeframes** : " + " | ".join(analysis["conflicts"]))
        st.caption("Les TF longs sont en conflit avec les TF courts — signe de prudence")

    # ─── Row 6: Proximité ICT (DataFrame) ──────────────────────────────────
    st.divider()
    st.subheader("📍 Proximité ICT")
    proximity = analysis.get("proximity", {})
    if proximity:
        order = ["OTE", "OB", "FVG", "GAP", "Discount", "Premium", "Equilibrium", "BSL", "SSL", "MSS"]
        icons = {
            "OTE": "🎯", "OB": "🧱", "FVG": "🕳️", "GAP": "〰️", "Discount": "🟢",
            "Premium": "🔴", "Equilibrium": "⚖️", "BSL": "⬆️", "SSL": "⬇️", "MSS": "💥"
        }
        dir_labels = {"bullish": "🟢 HAUSSIER", "bearish": "🔴 BAISSIER", "neutral": "🟡 NEUTRE"}

        rows = []
        for ctype in order:
            if ctype not in proximity:
                continue
            for a in proximity[ctype][:2]:
                icon = icons.get(ctype, "📍")
                rows.append({
                    "Concept": f"{icon} {ctype}",
                    "TF": a.tf,
                    "Direction": dir_labels.get(a.direction, a.direction.upper()),
                    "Zone": f"{a.level_low:.1f} – {a.level_high:.1f}",
                    "Distance": a.distance_label(),
                    "Force": f"{a.strength:.0%}",
                })

        if rows:
            df_prox = pd.DataFrame(rows)
            st.dataframe(
                df_prox,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Concept": st.column_config.TextColumn("🏷️ Concept", width="small"),
                    "TF": st.column_config.TextColumn("📡 TF", width="small"),
                    "Direction": st.column_config.TextColumn("Direction", width="medium"),
                    "Zone": st.column_config.TextColumn("🎯 Zone", width="medium"),
                    "Distance": st.column_config.TextColumn("📏 Distance", width="medium"),
                    "Force": st.column_config.TextColumn("💪 Force", width="small"),
                },
            )
    else:
        st.info("Aucune proximité ICT détectée.")

    # ─── Row 7: Setups de Trading (DataFrame) ──────────────────────────────
    st.divider()
    st.subheader("🎯 Setups de Trading (Proximité ICT)")
    setups = analysis.get("proximity_setups", [])
    if setups:
        rows = []
        for s in setups:
            direction = "🟢 LONG" if s.direction == "long" else "🔴 SHORT"
            rr = s.risk_reward()
            tfs_str = ', '.join(s.tfs) if s.tfs else ''
            tp2_str = f"{s.target_2:.1f}" if s.target_2 else "-"
            tp3_str = f"{s.target_3:.1f}" if s.target_3 else "-"
            rows.append({
                "Direction": direction,
                "Force": f"{s.strength:.0%}",
                "R:R": f"{rr}",
                "TFs": tfs_str,
                "Entrée": f"{s.entry_low:.1f} – {s.entry_high:.1f}",
                "SL": f"{s.stop_loss:.1f}",
                "TP1": f"{s.target_1:.1f}",
                "TP2": tp2_str,
                "TP3": tp3_str,
                "Raison Entrée": s.entry_reason,
                "Raison SL": s.sl_reason,
                "Raison TP": s.tp_reason,
            })

        if rows:
            df_setups = pd.DataFrame(rows)
            st.dataframe(
                df_setups,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Direction": st.column_config.TextColumn("🎯 Direction", width="small"),
                    "Force": st.column_config.TextColumn("💪 Force", width="small"),
                    "R:R": st.column_config.TextColumn("📊 R:R", width="small"),
                    "TFs": st.column_config.TextColumn("📡 TFs", width="small"),
                    "Entrée": st.column_config.TextColumn("💰 Entrée", width="medium"),
                    "SL": st.column_config.TextColumn("🛑 SL", width="medium"),
                    "TP1": st.column_config.TextColumn("TP1", width="small"),
                    "TP2": st.column_config.TextColumn("TP2", width="small"),
                    "TP3": st.column_config.TextColumn("TP3", width="small"),
                    "Raison Entrée": st.column_config.TextColumn("🎯 Raison Entrée", width="large"),
                    "Raison SL": st.column_config.TextColumn("🛑 Raison SL", width="large"),
                    "Raison TP": st.column_config.TextColumn("🎯 Raison TP", width="large"),
                },
            )
    else:
        st.info("Aucun setup de trading basé sur la proximité ICT.")

    # ─── Footer auto-refresh ──────────────────────────────────────────
    st.divider()
    st.caption(f"🔄 Dernière mise à jour: {analysis.get('timestamp', 'N/A')} | "
               f"Auto-refresh: {'ON' if st.session_state.autorefresh else 'OFF'} | "
               f"Données MT5 temps réel")
    if st.session_state.autorefresh:
        time.sleep(2)
        st.rerun()


if __name__ == "__main__":
    render_dashboard()
