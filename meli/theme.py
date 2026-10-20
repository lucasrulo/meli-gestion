"""Look & feel: tema oscuro futurista (glass + neón) para toda la app."""
import streamlit as st

C = {
    "bg": "#060A13",
    "surface": "rgba(17, 24, 42, 0.72)",
    "surface2": "#0F1628",
    "border": "rgba(139, 158, 255, 0.16)",
    "cyan": "#22D3EE",
    "violet": "#8B5CF6",
    "pink": "#EC4899",
    "yellow": "#FFE600",
    "text": "#E6EAF2",
    "muted": "#8A94A7",
    "ok": "#34D399",
    "warn": "#FBBF24",
    "err": "#F87171",
}
GRAD = f"linear-gradient(135deg, {C['cyan']} 0%, {C['violet']} 55%, {C['pink']} 100%)"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');

:root {{
  --bg:{C['bg']}; --surface:{C['surface']}; --surface2:{C['surface2']}; --border:{C['border']};
  --cyan:{C['cyan']}; --violet:{C['violet']}; --pink:{C['pink']}; --text:{C['text']}; --muted:{C['muted']};
  --grad:{GRAD};
}}

/* ---------- base ---------- */
html, body, [class*="css"], .stApp, .stMarkdown, p, label, input, textarea, button, li {{
  font-family: 'Inter', system-ui, sans-serif !important;
}}
[data-testid="stAppViewContainer"] {{
  background:
    radial-gradient(1200px 600px at 85% -10%, rgba(139,92,246,.18), transparent 60%),
    radial-gradient(900px 500px at -10% 10%, rgba(34,211,238,.12), transparent 55%),
    radial-gradient(800px 600px at 50% 120%, rgba(236,72,153,.08), transparent 60%),
    var(--bg) !important;
}}
[data-testid="stAppViewContainer"]::before {{   /* grilla sutil */
  content:""; position:fixed; inset:0; pointer-events:none; z-index:0;
  background-image: linear-gradient(rgba(139,158,255,.04) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(139,158,255,.04) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: radial-gradient(ellipse at 50% 0%, #000 30%, transparent 75%);
}}
[data-testid="stHeader"] {{ background: transparent !important; }}
[data-testid="stMainBlockContainer"], .block-container {{ padding-top: 2.2rem !important; max-width: 1400px; }}
#MainMenu, footer, [data-testid="stDecoration"] {{ visibility: hidden; height: 0; }}

h1, h2, h3, h4 {{ font-family: 'Space Grotesk', sans-serif !important; letter-spacing: -.01em; color: var(--text); }}
h2, h3 {{ font-weight: 600 !important; }}
[data-testid="stCaptionContainer"], .stCaption {{ color: var(--muted) !important; }}
code {{ font-family: 'JetBrains Mono', monospace !important; color: var(--cyan) !important;
       background: rgba(34,211,238,.08) !important; border-radius: 6px; }}
a {{ color: var(--cyan) !important; }}
hr {{ border-color: var(--border) !important; }}

/* ---------- sidebar ---------- */
[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, rgba(12,18,34,.96), rgba(7,11,20,.98)) !important;
  border-right: 1px solid var(--border);
  box-shadow: 8px 0 40px rgba(0,0,0,.35);
}}
[data-testid="stSidebarNavSeparator"] {{ border-color: var(--border) !important; }}
[data-testid="stSidebarNav"] a, [data-testid="stSidebarNavLink"] {{
  border-radius: 10px !important; margin: 1px 6px; transition: all .15s ease;
}}
[data-testid="stSidebarNavLink"]:hover {{ background: rgba(139,92,246,.12) !important; }}
[data-testid="stSidebarNavLink"][aria-current="page"] {{
  background: linear-gradient(90deg, rgba(34,211,238,.18), rgba(139,92,246,.10)) !important;
  box-shadow: inset 3px 0 0 var(--cyan);
}}
[data-testid="stNavSectionHeader"], [data-testid="stSidebarNavSectionHeader"] {{
  font-family: 'Space Grotesk', sans-serif !important; text-transform: uppercase;
  letter-spacing: .14em; font-size: .68rem !important; color: var(--muted) !important;
}}
[data-testid="stLogo"] {{ height: 3.1rem !important; max-width: 100%; }}

/* ---------- botones ---------- */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button, .stLinkButton > a {{
  border-radius: 12px !important; font-weight: 600 !important; letter-spacing: .01em;
  border: 1px solid var(--border) !important; background: var(--surface) !important; color: var(--text) !important;
  transition: transform .12s ease, box-shadow .2s ease, border-color .2s ease;
}}
.stButton > button:hover, .stDownloadButton > button:hover, .stLinkButton > a:hover {{
  border-color: rgba(34,211,238,.55) !important; box-shadow: 0 0 0 3px rgba(34,211,238,.08), 0 8px 24px rgba(34,211,238,.12);
  transform: translateY(-1px);
}}
button[kind="primary"], button[data-testid="stBaseButton-primary"], .stLinkButton > a[kind="primary"],
a[data-testid="stBaseLinkButton-primary"] {{
  background: var(--grad) !important; border: 0 !important; color: #fff !important;
  box-shadow: 0 6px 24px rgba(139,92,246,.35), inset 0 1px 0 rgba(255,255,255,.25);
}}
button[kind="primary"]:hover, button[data-testid="stBaseButton-primary"]:hover {{
  filter: brightness(1.08) saturate(1.1); box-shadow: 0 10px 34px rgba(236,72,153,.35);
}}
button:disabled {{ opacity: .45 !important; transform: none !important; box-shadow: none !important; }}

/* ---------- inputs ---------- */
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div, .stNumberInput > div > div,
[data-testid="stDateInput"] > div > div, [data-testid="stTimeInput"] > div > div {{
  background: rgba(10,15,28,.85) !important; border-radius: 12px !important;
  border: 1px solid var(--border) !important; transition: border-color .2s, box-shadow .2s;
}}
[data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within, [data-baseweb="select"] > div:focus-within {{
  border-color: var(--cyan) !important; box-shadow: 0 0 0 3px rgba(34,211,238,.15) !important;
}}
textarea {{ font-family: 'Inter', sans-serif !important; line-height: 1.5 !important; }}
[data-baseweb="tag"] {{ background: rgba(139,92,246,.25) !important; border: 1px solid rgba(139,92,246,.5); border-radius: 8px !important; }}
[data-testid="stFileUploaderDropzone"] {{
  background: rgba(10,15,28,.6) !important; border: 1.5px dashed rgba(34,211,238,.35) !important; border-radius: 14px !important;
}}

/* ---------- métricas ---------- */
[data-testid="stMetric"] {{
  background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 14px 18px;
  backdrop-filter: blur(10px); position: relative; overflow: hidden;
  box-shadow: 0 10px 30px rgba(0,0,0,.25);
}}
[data-testid="stMetric"]::before {{
  content:""; position:absolute; left:0; top:0; height:2px; width:100%; background: var(--grad); opacity:.85;
}}
[data-testid="stMetricLabel"] p {{ color: var(--muted) !important; text-transform: uppercase; letter-spacing: .08em; font-size: .72rem !important; }}
[data-testid="stMetricValue"] {{ font-family: 'Space Grotesk', sans-serif !important; font-weight: 700; color: var(--text); }}

/* ---------- tablas, tabs, expanders, alertas ---------- */
[data-testid="stDataFrame"], [data-testid="stDataEditor"], [data-testid="stTable"] {{
  border: 1px solid var(--border); border-radius: 14px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,.25);
}}
[data-baseweb="tab-list"] {{ gap: 6px; border-bottom: 1px solid var(--border); }}
[data-baseweb="tab"] {{
  border-radius: 10px 10px 0 0 !important; padding: 8px 14px !important; color: var(--muted) !important;
  font-family: 'Space Grotesk', sans-serif !important; font-weight: 600;
}}
[data-baseweb="tab"][aria-selected="true"] {{ color: var(--text) !important; background: rgba(34,211,238,.08) !important; }}
[data-baseweb="tab-highlight"] {{ background: var(--grad) !important; height: 3px !important; border-radius: 3px; }}
[data-testid="stExpander"] details {{
  background: var(--surface); border: 1px solid var(--border) !important; border-radius: 14px !important;
}}
[data-testid="stExpander"] summary:hover {{ color: var(--cyan) !important; }}
[data-testid="stAlert"] {{ border-radius: 14px !important; border: 1px solid var(--border); backdrop-filter: blur(6px); }}
[data-testid="stForm"] {{ background: var(--surface); border: 1px solid var(--border) !important; border-radius: 16px; }}
[data-testid="stProgress"] > div > div > div > div, .stProgress > div > div > div > div {{ background: var(--grad) !important; }}
[data-testid="stCheckbox"] label span[aria-checked="true"], [role="checkbox"][aria-checked="true"] {{
  background: var(--grad) !important; border-color: transparent !important;
}}
[data-testid="stToast"] {{ background: var(--surface2) !important; border: 1px solid var(--border); border-radius: 14px; }}
::-webkit-scrollbar {{ width: 10px; height: 10px; }}
::-webkit-scrollbar-thumb {{ background: rgba(139,158,255,.25); border-radius: 10px; }}
::-webkit-scrollbar-track {{ background: transparent; }}

/* ---------- componentes propios ---------- */
.mo-hero {{ position: relative; padding: 4px 0 18px; margin-bottom: 8px; }}
.mo-kicker {{
  display:inline-flex; align-items:center; gap:8px; font-family:'JetBrains Mono',monospace; font-size:.72rem;
  letter-spacing:.18em; text-transform:uppercase; color: var(--cyan);
  padding: 4px 10px; border: 1px solid rgba(34,211,238,.35); border-radius: 999px; background: rgba(34,211,238,.07);
}}
.mo-kicker::before {{ content:""; width:7px; height:7px; border-radius:50%; background: var(--cyan);
  box-shadow: 0 0 10px var(--cyan); animation: mo-pulse 2s infinite; }}
@keyframes mo-pulse {{ 0%,100% {{ opacity:1 }} 50% {{ opacity:.35 }} }}
.mo-title {{
  font-family:'Space Grotesk',sans-serif; font-weight:700; font-size: clamp(1.9rem, 3.2vw, 2.8rem); line-height:1.1;
  margin: 12px 0 6px; background: linear-gradient(90deg, #F1F5FF 0%, #C7D2FE 45%, var(--cyan) 100%);
  -webkit-background-clip:text; background-clip:text; color: transparent;
}}
.mo-sub {{ color: var(--muted); font-size: 1rem; max-width: 860px; }}
.mo-line {{ height:1px; margin-top:16px; background: linear-gradient(90deg, var(--cyan), rgba(139,92,246,.6), transparent); }}
.mo-card {{
  background: var(--surface); border:1px solid var(--border); border-radius:18px; padding:18px 18px 14px;
  backdrop-filter: blur(10px); height:100%; transition: transform .15s, border-color .2s, box-shadow .2s;
  box-shadow: 0 10px 30px rgba(0,0,0,.25);
}}
.mo-card:hover {{ transform: translateY(-2px); border-color: rgba(34,211,238,.45); box-shadow: 0 14px 40px rgba(34,211,238,.10); }}
.mo-card .ic {{ font-size: 1.4rem; width: 44px; height: 44px; display:grid; place-items:center; border-radius: 12px;
  background: linear-gradient(135deg, rgba(34,211,238,.18), rgba(139,92,246,.18)); border: 1px solid var(--border); }}
.mo-card h4 {{ margin: 12px 0 4px; font-size: 1.05rem; }}
.mo-card p {{ color: var(--muted); font-size: .88rem; margin: 0; min-height: 4.2em; }}
.mo-badge {{ display:inline-block; font-family:'JetBrains Mono',monospace; font-size:.7rem; padding:2px 8px; border-radius:999px;
  border:1px solid var(--border); color: var(--muted); }}
.mo-login {{ max-width: 420px; margin: 8vh auto 0; text-align:center; }}
.mo-login img {{ width: 84px; filter: drop-shadow(0 0 24px rgba(139,92,246,.55)); }}
</style>
"""


def apply_theme() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str = "", kicker: str = "") -> None:
    k = f'<span class="mo-kicker">{kicker}</span>' if kicker else ""
    s = f'<div class="mo-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(f'<div class="mo-hero">{k}<div class="mo-title">{title}</div>{s}<div class="mo-line"></div></div>',
                unsafe_allow_html=True)


def card(icon: str, title: str, text: str, badge: str = "") -> None:
    b = f'<div style="margin-top:10px"><span class="mo-badge">{badge}</span></div>' if badge else ""
    st.markdown(f'<div class="mo-card"><div class="ic">{icon}</div><h4>{title}</h4><p>{text}</p>{b}</div>',
                unsafe_allow_html=True)
