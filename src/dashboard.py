"""
Dashboard Streamlit pour le système de trading ICT.
Affichage temps réel des données MT5, signaux, positions, et KPIs.
"""

import time
import logging
import os
import subprocess
from typing import Dict, Optional
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import sys
sys.path.insert(0, '.')
import shutil
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
from src.setup_tracker import SetupTracker
from src.sessions import KillzoneConformity

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
    
    .session-badge.active.silver_bullet {
        background: #ff450044;
        border: 1px solid #ff4500;
        color: #ff4500;
        animation: pulse 2s infinite;
    }
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.7; }
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
        # Restaurer depuis les query params (survit au F5)
        params = st.query_params
        if "tfs" in params and params["tfs"]:
            saved_tfs = params["tfs"].split(",")
            # Filtrer pour ne garder que les TF valides
            saved_tfs = [tf for tf in saved_tfs if tf in TIMEFRAME_NAMES]
            if saved_tfs:
                st.session_state.active_tfs = saved_tfs
            else:
                st.session_state.active_tfs = list(TIMEFRAME_NAMES)
        else:
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


def _handle_fatal_error(error_name: str, error_msg: str, traceback_str: str):
    """Redémarre automatiquement le dashboard après une erreur transitoire.
    Protection anti-boucle : max 3 redémarrages en 60 secondes."""

    project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    restart_tracker = os.path.join(project_dir, '.codebuff_restart_log.txt')
    current_pid = os.getpid()

    # Anti-boucle : compter les redémarrages récents
    now = time.time()
    recent_restarts = 0
    if os.path.exists(restart_tracker):
        try:
            with open(restart_tracker, 'r') as f:
                for line in f:
                    try:
                        ts = float(line.strip())
                        if now - ts < 60:
                            recent_restarts += 1
                    except Exception:
                        pass
        except Exception:
            pass

    # Afficher le message d'erreur
    st.error(f"💥 Erreur lors de l'analyse : {error_name}: {error_msg}")
    with st.expander("🔍 Détails techniques"):
        st.code(traceback_str[:2000])

    if recent_restarts >= 3:
        st.error(
            "🚫 **Redémarrage automatique DÉSACTIVÉ** — trop d'erreurs en 60 secondes.\n\n"
            "Le code semble avoir un problème persistant. Vérifiez et corrigez le fichier concerné, "
            "puis relancez manuellement :\n\n"
            "```bash\npython main.py dashboard\n```"
        )
        try:
            os.remove(restart_tracker)
        except Exception:
            pass
        st.stop()

    # Logger ce restart
    try:
        with open(restart_tracker, 'a') as f:
            f.write(f"{now}\n")
    except Exception:
        pass

    # Afficher le compte à rebours et l'explication
    st.warning(
        f"🔄 **Redémarrage automatique dans 3 secondes...**\n\n"
        f"L'erreur vient probablement d'une modification du code pendant l'exécution.\n"
        f"Le dashboard va redémarrer proprement (cleanup cache + kill PID + restart).\n\n"
        f"📊 Redémarrages récents : **{recent_restarts + 1}/3** (max)"
    )

    st.info(
        "💡 **Pourquoi cette erreur ?** Le code a été modifié pendant que le dashboard tournait. "
        "Python a rechargé un module dans un état transitoire (ex: variable pas encore définie). "
        "Le redémarrage nettoie tout et repart sur une base propre."
    )

    # Écrire un micro-script Python qui fera le restart (plus fiable qu'un .bat)
    restart_py = os.path.join(project_dir, '.codebuff_restart.py')
    with open(restart_py, 'w', encoding='utf-8') as f:
        f.write(f'''import time, os, sys, subprocess, shutil

# Attendre que Streamlit ait rendu la page d'erreur
time.sleep(3)

# Tuer l'ancien processus
try:
    subprocess.run(["taskkill", "/f", "/pid", "{current_pid}"], capture_output=True, timeout=10)
except Exception:
    pass

time.sleep(1)

# Nettoyer les caches
project_dir = r"{project_dir}"
os.chdir(project_dir)
for root, dirs, files in os.walk("."):
    if ".git" in root or ".venv" in root:
        continue
    for d in dirs:
        if d == "__pycache__":
            shutil.rmtree(os.path.join(root, d), ignore_errors=True)
    for f in files:
        if f.endswith(".pyc"):
            try:
                os.remove(os.path.join(root, f))
            except Exception:
                pass

# Redémarrer le dashboard
subprocess.run([sys.executable, "main.py", "dashboard"])

# Nettoyer ce script de restart (ne plus encombrer le projet)
try:
    os.remove(__file__)
except Exception:
    pass
''')

    # Lancer le restart en processus détaché (fenêtre cachée)
    DETACHED = 0x00000008  # DETACHED_PROCESS
    CREATE_NO_WINDOW = 0x08000000
    subprocess.Popen(
        [sys.executable, restart_py],
        creationflags=DETACHED | CREATE_NO_WINDOW,
    )

    # Laisser Streamlit le temps de render avant que le restart ne tue le processus
    time.sleep(0.5)
    st.stop()


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
    try:
        all_sessions = st.session_state.session_detector.get_all_sessions()
    except Exception as e:
        st.error(f"⚠️ Erreur session detector: {e}")
        all_sessions = []
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
            # Sauvegarder dans les query params pour survie au F5
            st.query_params["tfs"] = ",".join(selected_tfs)
            st.session_state.data_engine.clear_cache()
            # Réinitialiser l'analyseur et le tracker (historique des setups, cache, etc.)
            try:
                if os.path.exists("mt5-reports/setup_tracker.json"):
                    os.remove("mt5-reports/setup_tracker.json")
                if os.path.exists("mt5-reports"):
                    shutil.rmtree("mt5-reports")
            except Exception:
                pass
            st.session_state.analyzer = ICTAnalyzer()
            st.session_state.last_refresh = 0  # Force un refresh complet
            st.rerun()

        st.caption(f"{len(selected_tfs)}/{len(TIMEFRAME_NAMES)} actifs")

        st.divider()
        st.subheader("🕐 Sessions")
        # Réutilise all_sessions calculé avant le sidebar
        for s in all_sessions:
            cls = "active" if s.active else "inactive"
            if s.name == "silver_bullet":
                cls += " silver_bullet"
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
    try:
        if st.session_state.autorefresh or now - st.session_state.last_refresh > 30:
            st.session_state.analyzer = ICTAnalyzer()
            analysis = st.session_state.analyzer.analyze_symbol(symbol, force_refresh=True, timeframes=active_tfs)
            st.session_state.last_refresh = now
        else:
            analysis = st.session_state.analyzer.analyze_symbol(symbol, timeframes=active_tfs)
    except Exception as e:
        # Survivre aux erreurs de code transitoires (ex: variable non définie entre 2 édits)
        import traceback
        _handle_fatal_error(type(e).__name__, str(e), traceback.format_exc())

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

    # Conformité killzone
    killzone_conf = analysis.get("killzone_conformity")
    if killzone_conf and not hasattr(killzone_conf, 'is_active'):
        killzone_conf = None  # Sérialisation invalide, ignorer

    # Le décompte countdown_str est déjà calculé avant le sidebar
    if countdown_str:
        macro_label_full = f"{macro['macro_label']} — {countdown_str}"
    else:
        macro_label_full = macro["macro_label"]

    # Ajouter la conformité killzone dans la bannière
    if killzone_conf and killzone_conf.is_active:
        conf_icon = {"conforme": "✅", "partiel": "⚠️", "non_conforme": "❌"}.get(killzone_conf.conformity, "")
        conf_color = killzone_conf.conformity_color()
        macro_label_full += f"  |  {conf_icon} Killzone: {killzone_conf.conformity_label()}"

    st.markdown(
        f'<div style="background:linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);'
        f'border:1px solid {macro_color};border-radius:12px;padding:12px 20px;'
        f'margin-bottom:12px;text-align:center;">'
        f'<span style="font-size:1.1rem;color:{macro_color};font-weight:700;">{macro_label_full}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Alerte conformité si non-conforme
    if killzone_conf and killzone_conf.warning:
        wcol = "#ff4444" if killzone_conf.conformity == "non_conforme" else "#ffaa00"
        st.markdown(
            f'<div style="background:#2a1a1a;border:1px solid {wcol};border-radius:8px;'
            f'padding:8px 16px;margin-bottom:12px;font-size:0.85rem;color:{wcol};">'
            f'{killzone_conf.warning}</div>',
            unsafe_allow_html=True,
        )

    # ─── Row 1: Explications ICT (expandeur) ────────────────────────────
    with st.expander("📖 Guide ICT — Killzones & Macro", expanded=False):
        kz_now = macro.get("active_killzone", "")
        # Toutes les killzones actives (pas seulement la primaire)
        all_active_labels = [s.label for s in all_sessions if s.active]

        def _kz_row(emoji, name, utc, desc, active_labels):
            """Génère une ligne de tableau killzone avec mise en évidence si active."""
            is_active = name in active_labels
            if is_active:
                return f"| 🟢👉 **{emoji} {name}** | {utc} | **{desc}** |"
            return f"| {emoji} {name} | {utc} | {desc} |"

        def _att_li(name, advice, active_labels):
            """Génère une ligne d'attitude avec highlight si active."""
            is_active = name in active_labels
            if is_active:
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
            kz_rows = "\n".join(_kz_row(*k[:4], all_active_labels) for k in kz_info)
            st.markdown(f"""**🔫 Kill Zones** — Créneaux horaires à forte activité

| Zone | UTC | Comportement |
|------|-----|--------------|
{kz_rows}
""")

            # Attitude avec la ligne active en évidence
            att_lines = "\n".join(_att_li(k[1], k[4], all_active_labels) for k in kz_info)
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
    # Préfixes cerclés pour que le tri alphabétique suive l'ordre hiérarchique ICT
    _tf_sort_prefix = {tf: chr(0x2460 + i) for i, tf in enumerate(TIMEFRAME_HIERARCHY)}
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
                prefix = _tf_sort_prefix.get(a.tf, "")
                rows.append({
                    "Concept": f"{icon} {ctype}",
                    "TF": f"{prefix} {a.tf}" if prefix else a.tf,
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
            # Préfixer la première TF pour que le tri alphabétique suive l'ordre hiérarchique
            if s.tfs:
                prefix = _tf_sort_prefix.get(s.tfs[0], "")
                tfs_str = f"{prefix} {', '.join(s.tfs)}" if prefix else ', '.join(s.tfs)
            else:
                tfs_str = ''
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

    # ─── Row 8: Key Levels ────────────────────────────────────────────
    st.divider()
    st.subheader("🔑 Key Levels — Niveaux de Liquidité")
    key_levels = analysis.get("key_levels", [])
    if key_levels:
        price_now = analysis.get("current_price", {}).get("bid", 0)
        kl_rows = []
        order_kl = ["PMH", "PML", "PWH", "PWL", "PDH", "PDL"]
        for lt in order_kl:
            for kl in key_levels:
                if kl.level_type == lt:
                    dist = price_now - kl.level
                    liq_type = "🟢 BSL" if kl.liquidity_type == "BSL" else "🔴 SSL"
                    status = "🔥 Sweepé" if kl.swept else "✅ Intact"
                    status_color = "#ff4444" if kl.swept else "#00ff88"
                    kl_rows.append({
                        "Niveau": lt,
                        "Label": kl.label,
                        "Prix": f"{kl.level:.1f}",
                        "Liquidité": liq_type,
                        "TF": kl.source_tf,
                        "Distance": f"{dist:+.1f}",
                        "Statut": status,
                    })

        if kl_rows:
            df_kl = pd.DataFrame(kl_rows)
            st.dataframe(
                df_kl,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Niveau": st.column_config.TextColumn("🏔️ Niveau", width="small"),
                    "Label": st.column_config.TextColumn("📝 Description", width="medium"),
                    "Prix": st.column_config.TextColumn("💰 Prix", width="small"),
                    "Liquidité": st.column_config.TextColumn("🎯 Type", width="small"),
                    "TF": st.column_config.TextColumn("📡 TF", width="small"),
                    "Distance": st.column_config.TextColumn("📏 Distance", width="small"),
                    "Statut": st.column_config.TextColumn("🔒 Statut", width="small"),
                },
            )
    else:
        st.info("Aucun key level détecté. Active les timeframes D1, W1 ou MN1.")

    # ─── Row 9: Suivi des Setups (Tracker) ────────────────────────────
    st.divider()
    st.subheader("📊 Suivi des Setups de Trading")

    tracker_stats = analysis.get("setup_tracker_stats", {})
    tracker_active = analysis.get("setup_tracker_active", [])
    predictive = analysis.get("predictive_score", {})

    col_track_stats, col_track_active = st.columns([1, 2])

    with col_track_stats:
        total = tracker_stats.get("total_tracked", 0)
        active_count = tracker_stats.get("active", 0)
        completed = tracker_stats.get("completed", 0)
        wins = tracker_stats.get("wins", 0)
        losses = tracker_stats.get("losses", 0)
        win_rate = tracker_stats.get("win_rate", 0)
        avg_rr = tracker_stats.get("avg_rr_realized", 0)

        st.markdown("#### 📈 Performance Globale")

        cols = st.columns(2)
        with cols[0]:
            render_metric("Total Trackés", str(total), "neutral")
            render_metric("Actifs", str(active_count), "neutral")
        with cols[1]:
            wr_color = "positive" if win_rate >= 50 else ("neutral" if win_rate >= 30 else "negative")
            render_metric("Win Rate", f"{win_rate}%", wr_color)
            render_metric("R:R Moyen", f"{avg_rr}", "positive" if avg_rr >= 1.5 else "neutral")

        cols2 = st.columns(2)
        with cols2[0]:
            render_metric("✅ Wins", str(wins), "positive")
        with cols2[1]:
            render_metric("❌ Losses", str(losses), "negative")

        # Par direction — métriques séparées LONG / SHORT
        long_data = tracker_stats.get("long", {})
        short_data = tracker_stats.get("short", {})
        if long_data or short_data:
            st.markdown("**Par direction :**")
            lw = long_data.get('wins', 0)
            ll = long_data.get('losses', 0)
            sw = short_data.get('wins', 0)
            sl = short_data.get('losses', 0)
            lwr = round(lw / (lw + ll) * 100, 1) if (lw + ll) > 0 else 0
            swr = round(sw / (sw + sl) * 100, 1) if (sw + sl) > 0 else 0

            dcols = st.columns(2)
            with dcols[0]:
                st.markdown(
                    f'<div class="metric-card" style="border-color:#00ff88;">'
                    f'<div class="label">🟢 LONG</div>'
                    f'<div class="value positive">{lw}W / {ll}L</div>'
                    f'<div style="font-size:0.9rem;color:#888;margin-top:2px;">'
                    f'Win Rate: <span style="color:{"#00ff88" if lwr >= 50 else "#ffaa00" if lwr >= 30 else "#ff4444"};">{lwr}%</span>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )
            with dcols[1]:
                st.markdown(
                    f'<div class="metric-card" style="border-color:#ff4444;">'
                    f'<div class="label">🔴 SHORT</div>'
                    f'<div class="value negative">{sw}W / {sl}L</div>'
                    f'<div style="font-size:0.9rem;color:#888;margin-top:2px;">'
                    f'Win Rate: <span style="color:{"#00ff88" if swr >= 50 else "#ffaa00" if swr >= 30 else "#ff4444"};">{swr}%</span>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )

        # Par source
        by_source = tracker_stats.get("by_source", {})
        if by_source:
            st.markdown("**Par source :**")
            for src, counts in by_source.items():
                total_src = counts.get("wins", 0) + counts.get("losses", 0)
                wr_src = counts.get("wins", 0) / total_src * 100 if total_src > 0 else 0
                st.caption(f"  {src}: {counts.get('wins', 0)}W/{counts.get('losses', 0)}L ({wr_src:.0f}%)")

        # Score prédictif (basé sur l'historique similaire)
        if predictive and predictive.get("similar_count", 0) >= 3:
            st.divider()
            st.markdown("#### 🔮 Score Prédictif")
            pred_score = predictive.get("predictive_score", 50)
            pred_conf = predictive.get("confidence", "low")
            pred_color = (
                "#00ff88" if pred_score >= 65 else
                "#ffaa00" if pred_score >= 45 else "#ff4444"
            )
            conf_badge = {"high": "✅ Fiable", "medium": "⚠️ Modéré", "low": "❓ Limité"}.get(pred_conf, "")
            st.markdown(
                f'<div style="border:1px solid {pred_color};border-radius:8px;padding:12px;text-align:center;">'
                f'<div style="font-size:0.7rem;color:#888;text-transform:uppercase;">'
                f'Basé sur {predictive.get("similar_count", 0)} setups similaires</div>'
                f'<div style="font-size:1.3rem;color:{pred_color};font-weight:700;">'
                f'{predictive["verdict"]}</div>'
                f'<div style="font-size:0.8rem;color:#888;margin-top:4px;">'
                f'WR similaire: {predictive.get("similar_win_rate", 0)}% vs Global: {predictive.get("global_win_rate", 0)}% | '
                f'R:R similaire: {predictive.get("similar_avg_rr", 0)} | {conf_badge}'
                f'</div></div>',
                unsafe_allow_html=True,
            )
            # Top 3 setups similaires
            top_similar = predictive.get("top_similar", [])
            if top_similar:
                st.caption("**Setups passés les plus similaires :**")
                for ts in top_similar:
                    outcome_icon = "✅" if ts["win"] else "❌"
                    dir_icon = "🟢" if ts["direction"] == "long" else "🔴"
                    sim_pct = f"{ts['similarity_score']:.0%}"
                    st.caption(
                        f"  {outcome_icon} {dir_icon} {ts['killzone_active']} | "
                        f"{ts['macro_bias']} | Similarité: {sim_pct}"
                    )

    with col_track_active:
        st.markdown("#### 🔄 Setups Actifs")
        if tracker_active:
            EXPIRY_HOURS = 168  # 7 jours
            now_dt = datetime.now()
            active_rows = []
            for ts in tracker_active[:10]:
                entry = ts.entry_mid
                direction_label = ts.get_direction_label()

                # ── Temps de vie écoulé ──
                detected_dt = datetime.fromisoformat(ts.detected_at) if ts.detected_at else now_dt
                hours_lived = (now_dt - detected_dt).total_seconds() / 3600
                hours_remaining = max(0, EXPIRY_HOURS - hours_lived)
                time_pct = round(min(hours_lived / EXPIRY_HOURS * 100, 100), 0)

                # Format lisible
                if hours_lived < 1:
                    age_str = f"{int(hours_lived * 60)}min"
                elif hours_lived < 24:
                    age_str = f"{int(hours_lived)}h {int(hours_lived % 1 * 60)}m"
                else:
                    days = int(hours_lived / 24)
                    h = int(hours_lived % 24)
                    age_str = f"{days}j {h}h"

                # Time remaining for display
                if hours_remaining < 1:
                    expiry_str = f"< 1min"
                elif hours_remaining < 24:
                    expiry_str = f"{int(hours_remaining)}h"
                else:
                    expiry_str = f"{int(hours_remaining / 24)}j"

                # ── R:R du setup ──
                rr_val = ts.risk_reward()

                active_rows.append({
                    "ID": ts.id,
                    "Dir.": direction_label,
                    "Entrée": f"{ts.entry_mid:.1f}",
                    "SL": f"{ts.stop_loss:.1f}",
                    "TP1": f"{ts.target_1:.1f}",
                    "R:R": f"1:{rr_val:.1f}" if rr_val >= 1.0 else f"1:{rr_val:.2f}",
                    "Force": f"{ts.strength:.0%}",
                    "Âge": age_str,
                    "Progrès": f"{time_pct:.0f}%",  # String formaté pour affichage
                    "_prog_pct": time_pct,             # Valeur numérique cachée pour le code couleur
                    "Expire": expiry_str,
                    "Détecté": ts.detected_at[:16] if ts.detected_at else "",
                })

            if active_rows:
                df_active = pd.DataFrame(active_rows)

                # Code couleur sur _prog_pct : vert > 50% restant, orange 25-50%, rouge < 25%
                def _color_progress(v):
                    remaining = 100 - v  # % de temps restant avant expiration
                    if remaining > 50:
                        return 'color: #00ff88; font-weight: bold'
                    elif remaining > 25:
                        return 'color: #ffaa00; font-weight: bold'
                    else:
                        return 'color: #ff4444; font-weight: bold'

                styled = df_active.style.map(_color_progress, subset=['_prog_pct'])

                st.dataframe(
                    styled,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "ID": st.column_config.TextColumn("🆔 ID", width="small"),
                        "Dir.": st.column_config.TextColumn("🎯 Dir", width="small"),
                        "Entrée": st.column_config.TextColumn("💰 Entrée", width="small"),
                        "SL": st.column_config.TextColumn("🛑 SL", width="small"),
                        "TP1": st.column_config.TextColumn("TP1", width="small"),
                        "R:R": st.column_config.TextColumn("📊 R:R", width="small"),
                        "Force": st.column_config.TextColumn("💪 Force", width="small"),
                        "Âge": st.column_config.TextColumn("⏱️ Âge", width="small"),
                        "Progrès": st.column_config.TextColumn(
                            "⌛ Expire",
                            help="% du temps d'expiration écoulé (168h max). Vert = récent, Orange = moyen, Rouge = expire bientôt",
                        ),
                        "_prog_pct": st.column_config.Column(" ", width="0"),  # Caché (largeur nulle)
                        "Expire": st.column_config.TextColumn("⏰ Restant", width="small"),
                        "Détecté": st.column_config.TextColumn("🕐 Détecté", width="medium"),
                    },
                )
        else:
            st.info("Aucun setup actif en suivi. Les setups détectés apparaîtront ici.")

    # ─── Row 9: Conformité Killzone ──────────────────────────────────
    if killzone_conf and killzone_conf.is_active:
        st.divider()
        st.subheader("🔫 Conformité Killzone")

        col_conf, col_details = st.columns([1, 2])

        with col_conf:
            conf_label = killzone_conf.conformity_label()
            conf_color = killzone_conf.conformity_color()
            score_pct = f"{killzone_conf.conformity_score:.0%}"

            st.markdown(
                f'<div style="border:2px solid {conf_color};border-radius:12px;padding:20px;text-align:center;">'
                f'<div style="font-size:0.8rem;color:#888;text-transform:uppercase;">Conformité {killzone_conf.killzone_label}</div>'
                f'<div style="font-size:1.5rem;color:{conf_color};font-weight:700;margin-top:8px;">{conf_label}</div>'
                f'<div style="font-size:1.2rem;color:{conf_color};margin-top:4px;">{score_pct}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        with col_details:
            st.markdown(f"**Comportement attendu ({killzone_conf.killzone_label}) :**")
            st.caption(killzone_conf.expected_behavior)
            st.markdown(f"**Comportement observé :** {killzone_conf.actual_behavior}")
            st.markdown("**Détails :**")
            for detail in killzone_conf.details:
                if detail.startswith("✅"):
                    st.success(detail)
                elif detail.startswith("⚠️"):
                    st.warning(detail)
                else:
                    st.info(detail)

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
