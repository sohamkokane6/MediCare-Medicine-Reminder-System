import html
import re
import sqlite3
from pathlib import Path
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st
import plotly.express as px

DB = Path(__file__).with_name("medicare.db")
st.set_page_config(page_title="MediCare | Medicine Reminder", page_icon="💊", layout="wide",
                   initial_sidebar_state="expanded")

# ----------------------------------------------------------------------------------------
# Database / business logic (unchanged)
# ----------------------------------------------------------------------------------------
def connect():
    con = sqlite3.connect(DB, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS medicines(
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, dosage TEXT NOT NULL,
            frequency TEXT NOT NULL, times TEXT NOT NULL, start_date TEXT NOT NULL,
            end_date TEXT, instructions TEXT DEFAULT '', notes TEXT DEFAULT '',
            active INTEGER DEFAULT 1, created_at TEXT NOT NULL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS dose_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, medicine_id INTEGER NOT NULL,
            scheduled_date TEXT NOT NULL, scheduled_time TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('Taken','Skipped')), recorded_at TEXT NOT NULL,
            UNIQUE(medicine_id, scheduled_date, scheduled_time),
            FOREIGN KEY(medicine_id) REFERENCES medicines(id))""")
        con.commit()

def medicines(active_only=False):
    with connect() as con:
        q = "SELECT * FROM medicines" + (" WHERE active=1" if active_only else "") + " ORDER BY active DESC,name"
        return pd.DataFrame([dict(r) for r in con.execute(q).fetchall()])

def logs():
    with connect() as con:
        q = """SELECT l.*,m.name AS medicine_name,m.dosage FROM dose_logs l
               JOIN medicines m ON m.id=l.medicine_id
               ORDER BY scheduled_date DESC,scheduled_time DESC"""
        return pd.DataFrame([dict(r) for r in con.execute(q).fetchall()])

def add_medicine(name,dosage,frequency,times,start,end,instructions,notes):
    with connect() as con:
        con.execute("""INSERT INTO medicines(name,dosage,frequency,times,start_date,end_date,
                    instructions,notes,active,created_at) VALUES(?,?,?,?,?,?,?,?,1,?)""",
                    (name.strip(),dosage.strip(),frequency,",".join(times),start.isoformat(),
                     end.isoformat() if end else None,instructions.strip(),notes.strip(),
                     datetime.now().isoformat(timespec="seconds")))
        con.commit()

def mark_dose(mid,day,tm,status):
    with connect() as con:
        con.execute("""INSERT INTO dose_logs(medicine_id,scheduled_date,scheduled_time,status,recorded_at)
                       VALUES(?,?,?,?,?) ON CONFLICT(medicine_id,scheduled_date,scheduled_time)
                       DO UPDATE SET status=excluded.status,recorded_at=excluded.recorded_at""",
                    (int(mid),day,tm,status,datetime.now().isoformat(timespec="seconds")))
        con.commit()

def scheduled(meds, history, day):
    result=[]
    for _,m in meds.iterrows():
        start=date.fromisoformat(m["start_date"])
        end=date.fromisoformat(m["end_date"]) if m["end_date"] else None
        if not int(m["active"]) or day < start or (end and day > end):
            continue
        for tm in m["times"].split(","):
            found=history[(history.medicine_id==m["id"]) & (history.scheduled_date==day.isoformat()) &
                          (history.scheduled_time==tm)] if not history.empty else pd.DataFrame()
            result.append({"id":int(m["id"]),"name":m["name"],"dosage":m["dosage"],"time":tm,
                           "instructions":m["instructions"] or "—",
                           "status":found.iloc[0]["status"] if not found.empty else "Pending"})
    return sorted(result,key=lambda x:x["time"])

init_db()
all_meds=medicines()
active_meds=medicines(True)
history=logs()
today=date.today()

# ----------------------------------------------------------------------------------------
# UI helpers
# ----------------------------------------------------------------------------------------
def _ver():
    try:
        return tuple(int(n) for n in re.findall(r"\d+", st.__version__)[:2])
    except Exception:
        return (0, 0)

# Newer Streamlit replaces use_container_width with width="stretch"
STRETCH = {"width": "stretch"} if _ver() >= (1, 50) else {"use_container_width": True}

def stretch_call(fn, *a, **k):
    try:
        return fn(*a, **STRETCH, **k)
    except Exception:
        return fn(*a, use_container_width=True, **k)

def esc(v):
    """Escape user text before placing it in custom HTML."""
    return (html.escape(str(v)).replace("$", "&#36;").replace("\r", "").replace("\n", "<br>"))

def md(markup, target=st):
    target.markdown(markup, unsafe_allow_html=True)

def card(key):
    """A styled white card. Falls back to a plain bordered container on older Streamlit."""
    try:
        return st.container(key=key)
    except TypeError:
        return st.container(border=True)

def page_header(icon, title, sub):
    md(f'<div class="page-head"><div class="page-icon">{icon}</div><div>'
       f'<div class="page-title">{esc(title)}</div><div class="page-sub">{esc(sub)}</div></div></div>')

def section_title(text, hint=""):
    h = f'<span class="section-hint">{esc(hint)}</span>' if hint else ""
    md(f'<div class="section-title">{esc(text)}{h}</div>')

def empty_state(icon, title, text):
    md(f'<div class="empty"><div class="empty-icon">{icon}</div><div class="empty-title">{esc(title)}</div>'
       f'<div class="empty-text">{esc(text)}</div></div>')

def stat_cards(items):
    cells = "".join(
        f'<div class="stat stat-{tone}"><div class="stat-icon">{icon}</div><div class="stat-body">'
        f'<div class="stat-value">{value}</div><div class="stat-label">{esc(label)}</div></div></div>'
        for icon, label, value, tone in items)
    md(f'<div class="stats">{cells}</div>')

def is_overdue(day, tm):
    try:
        return datetime.combine(day, datetime.strptime(tm, "%H:%M").time()) < datetime.now()
    except ValueError:
        return False

def status_pill(status, day=None, tm=None):
    if status == "Pending" and day is not None and is_overdue(day, tm):
        return '<span class="pill pill-overdue">● Overdue</span>'
    cls = {"Taken": "taken", "Skipped": "skipped", "Pending": "pending"}.get(status, "pending")
    icon = {"Taken": "✓", "Skipped": "⏭", "Pending": "●"}.get(status, "●")
    return f'<span class="pill pill-{cls}">{icon} {esc(status)}</span>'

def dose_info(x):
    return (f'<div class="dose-title"><span class="time-chip">{esc(x["time"])}</span>'
            f'<span class="dose-name">{esc(x["name"])}</span></div>'
            f'<div class="dose-meta">{esc(x["dosage"])} · {esc(x["instructions"])}</div>')

CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root{color-scheme:light;--navy:#0B2545;--navy2:#13315C;--blue:#1F6FD0;--blue-d:#1A5DB3;--teal:#0EA5A4;
--ink:#172B4D;--muted:#5B6B82;--line:#E2E8F0;--bg:#F4F7FB;--card:#FFFFFF}
html,body,.stApp{background:var(--bg)!important;color:var(--ink)}
.stApp :is(p,h1,h2,h3,h4,h5,h6,label,li,input,textarea,button,th,td){font-family:'Inter',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif}

/* chrome */
#MainMenu,footer,[data-testid="stDeployButton"],[data-testid="stDecoration"]{display:none!important}
header[data-testid="stHeader"]{background:transparent!important}
[data-testid="stExpandSidebarButton"],[data-testid="collapsedControl"]{color:var(--ink)!important}
.block-container,[data-testid="stMainBlockContainer"]{max-width:1280px;padding:3.2rem 2rem 3rem}

/* text visibility in the main area */
[data-testid="stMain"] :is(h1,h2,h3,h4,h5,h6,label,p,li,th,td),
section.main :is(h1,h2,h3,h4,h5,h6,label,p,li,th,td){color:var(--ink)}
[data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] *{color:var(--muted)!important}

/* sidebar */
section[data-testid="stSidebar"],section[data-testid="stSidebar"]>div{background:linear-gradient(180deg,var(--navy) 0%,var(--navy2) 100%)!important}
section[data-testid="stSidebar"] :is(p,span,label,div,li,h1,h2,h3){color:#E8EEF7}
section[data-testid="stSidebar"] hr{border-color:rgba(255,255,255,.14)}
.brand{display:flex;align-items:center;gap:12px;padding:6px 4px 14px}
.brand-logo{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;
background:linear-gradient(135deg,#1F6FD0,#0EA5A4);font-size:22px;box-shadow:0 6px 16px rgba(14,165,164,.35)}
.brand-name{font-size:20px;font-weight:800;color:#fff!important;line-height:1.1}
.brand-tag{font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:#9FB6D3!important;margin-top:3px}
.side-label{font-size:11px;font-weight:700;letter-spacing:.14em;color:#8FA8C8!important;margin:6px 4px 4px}
.side-date{background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.12);border-radius:12px;padding:10px 12px;
font-size:13px;font-weight:600;color:#fff!important}
.side-note{font-size:12px;line-height:1.5;color:#A9BDD8!important;margin-top:10px}
section[data-testid="stSidebar"] div[role="radiogroup"]{gap:4px}
section[data-testid="stSidebar"] div[role="radiogroup"]>label{padding:10px 12px;border-radius:10px;width:100%;
cursor:pointer;transition:background .15s ease;margin:0}
section[data-testid="stSidebar"] div[role="radiogroup"]>label:hover{background:rgba(255,255,255,.09)}
section[data-testid="stSidebar"] div[role="radiogroup"]>label:has(input:checked){background:rgba(255,255,255,.16);box-shadow:inset 3px 0 0 var(--teal)}
section[data-testid="stSidebar"] div[role="radiogroup"]>label p{color:#E8EEF7!important;font-weight:600;font-size:14.5px}

/* page header, sections */
.page-head{display:flex;align-items:center;gap:14px;margin:0 0 1.2rem}
.page-icon{width:50px;height:50px;border-radius:14px;display:flex;align-items:center;justify-content:center;font-size:24px;
background:linear-gradient(135deg,#E3EEFC,#DDF5F3);border:1px solid #D4E3F6;flex:none}
.page-title{font-size:28px;font-weight:800;color:var(--ink)!important;line-height:1.15;letter-spacing:-.01em}
.page-sub{font-size:14px;color:var(--muted)!important;margin-top:3px}
.section-title{font-size:17px;font-weight:700;color:var(--ink)!important;margin:1.3rem 0 .7rem;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.section-hint{font-size:12.5px;font-weight:500;color:var(--muted)!important}

/* hero */
.hero{position:relative;overflow:hidden;border-radius:18px;padding:24px 28px;margin-bottom:16px;
background:linear-gradient(120deg,#0B2545 0%,#1F6FD0 60%,#0EA5A4 100%);box-shadow:0 10px 28px rgba(31,111,208,.25)}
.hero:after{content:"";position:absolute;right:-60px;top:-60px;width:220px;height:220px;border-radius:50%;background:rgba(255,255,255,.08);pointer-events:none}
.hero-eyebrow{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#CFE3FA!important;font-weight:600}
.hero-title{font-size:30px;font-weight:800;color:#fff!important;margin:4px 0 4px;line-height:1.15}
.hero-sub{font-size:14.5px;color:#E6F1FF!important}
.progress{height:9px;border-radius:99px;background:rgba(255,255,255,.25);margin-top:16px;overflow:hidden;max-width:460px}
.progress-bar{height:100%;border-radius:99px;background:#fff}
.progress-label{font-size:12.5px;color:#E6F1FF!important;margin-top:7px;font-weight:600}

/* stat cards (CSS grid = responsive) */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin:6px 0 4px}
.stat{display:flex;align-items:center;gap:14px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;box-shadow:0 1px 2px rgba(16,24,40,.04)}
.stat-icon{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:20px;flex:none}
.stat-blue .stat-icon{background:#E3EEFC}.stat-teal .stat-icon{background:#D8F3F1}
.stat-green .stat-icon{background:#DCFCE7}.stat-amber .stat-icon{background:#FEF3C7}.stat-red .stat-icon{background:#FEE2E2}
.stat-value{font-size:26px;font-weight:800;color:var(--ink)!important;line-height:1.1}
.stat-label{font-size:13px;color:var(--muted)!important;font-weight:500;margin-top:2px}

/* cards (st.container(key="card_...")) */
[class*="st-key-card"]{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 18px;
box-shadow:0 1px 2px rgba(16,24,40,.04);transition:box-shadow .15s ease,border-color .15s ease;margin-bottom:2px}
[class*="st-key-card"]:hover{box-shadow:0 6px 18px rgba(16,24,40,.08);border-color:#CFDAEA}
[class*="st-key-card"] [data-testid="stHorizontalBlock"],
[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"]{align-items:center}
.dose-title{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.time-chip{background:#E3EEFC;color:#1A5DB3!important;font-weight:700;font-size:13px;padding:3px 10px;border-radius:8px;font-variant-numeric:tabular-nums}
.dose-name{font-size:16px;font-weight:700;color:var(--ink)!important}
.dose-meta{font-size:13px;color:var(--muted)!important;margin-top:4px}
.pill{display:inline-block;padding:4px 12px;border-radius:99px;font-size:12.5px;font-weight:700;white-space:nowrap}
.pill-taken,.pill-active{background:#DCFCE7;color:#166534!important}
.pill-pending{background:#FEF3C7;color:#92400E!important}
.pill-skipped{background:#FEE2E2;color:#991B1B!important}
.pill-overdue{background:#FFEDD5;color:#9A3412!important}
.pill-archived{background:#E2E8F0;color:#475569!important}
.med-name{font-size:18px;font-weight:800;color:var(--ink)!important}
.med-meta{font-size:13.5px;color:var(--ink)!important;margin-top:5px}
.med-meta b{color:var(--muted)!important;font-weight:600;margin-right:3px}
.sep{color:#A0AEC0!important;margin:0 6px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:9px}
.med-dates{font-size:12.5px;color:var(--muted)!important;margin-top:9px}
.kv{font-size:13.5px;color:var(--ink)!important;margin-bottom:8px;line-height:1.45}
.kv span{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted)!important;font-weight:700;margin-bottom:1px}

/* empty / callouts */
.empty{background:var(--card);border:1.5px dashed #C5D3E6;border-radius:16px;padding:34px 20px;text-align:center}
.empty-icon{font-size:34px}.empty-title{font-size:17px;font-weight:700;color:var(--ink)!important;margin-top:6px}
.empty-text{font-size:14px;color:var(--muted)!important;margin-top:4px}
.callout{background:#EAF3FE;border:1px solid #CFE2F8;border-radius:12px;padding:12px 14px;font-size:13.5px;line-height:1.5;color:#1E3A5F!important;margin-top:10px}
.callout.warn{background:#FFF7E6;border-color:#FCE2A8;color:#7A4B07!important}
.info-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}
.info-card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;box-shadow:0 1px 2px rgba(16,24,40,.04)}
.info-card h4{margin:0 0 6px;font-size:15px;font-weight:700;color:var(--ink)!important}
.info-card p{margin:0;font-size:13.5px;line-height:1.55;color:var(--muted)!important}
.info-card code{background:#EEF3FA;color:#1A5DB3;padding:2px 6px;border-radius:6px;font-size:12.5px}

/* buttons: always visible + clickable */
:is(.stButton,[data-testid="stButton"],.stDownloadButton,[data-testid="stDownloadButton"],[data-testid="stFormSubmitButton"]) button{
min-height:44px;width:100%;border-radius:10px;font-weight:600;white-space:nowrap;cursor:pointer!important;pointer-events:auto!important;
background:#FFFFFF;color:var(--ink);border:1px solid #CBD5E1;box-shadow:0 1px 1px rgba(16,24,40,.04);transition:all .15s ease}
:is(.stButton,[data-testid="stButton"],.stDownloadButton,[data-testid="stDownloadButton"],[data-testid="stFormSubmitButton"]) button p{color:inherit!important;margin:0;font-weight:600}
:is(.stButton,[data-testid="stButton"],.stDownloadButton,[data-testid="stDownloadButton"],[data-testid="stFormSubmitButton"]) button:hover{
background:#EFF6FF;border-color:var(--blue);color:var(--blue-d)}
:is(.stButton,[data-testid="stButton"],[data-testid="stFormSubmitButton"]) button:is([kind="primary"],[kind="primaryFormSubmit"],[data-testid="stBaseButton-primary"],[data-testid="stBaseButton-primaryFormSubmit"]){
background:var(--blue)!important;border-color:var(--blue)!important;color:#FFFFFF!important;box-shadow:0 4px 12px rgba(31,111,208,.28)}
:is(.stButton,[data-testid="stButton"],[data-testid="stFormSubmitButton"]) button:is([kind="primary"],[kind="primaryFormSubmit"],[data-testid="stBaseButton-primary"],[data-testid="stBaseButton-primaryFormSubmit"]):hover{
background:var(--blue-d)!important;border-color:var(--blue-d)!important;color:#FFFFFF!important}
:is(.stButton,[data-testid="stButton"],.stDownloadButton,[data-testid="stDownloadButton"],[data-testid="stFormSubmitButton"]) button:focus-visible{outline:3px solid rgba(31,111,208,.35);outline-offset:2px}
:is(.stButton,[data-testid="stButton"],.stDownloadButton,[data-testid="stDownloadButton"],[data-testid="stFormSubmitButton"]) button:disabled{opacity:.55;cursor:not-allowed!important}
.stDownloadButton button,[data-testid="stDownloadButton"] button{width:auto;min-width:230px}

/* inputs: dark text on white, always */
[data-baseweb="input"],[data-baseweb="base-input"],[data-baseweb="textarea"],[data-baseweb="select"]>div{
background:#FFFFFF!important;border-color:#CBD5E1!important;border-radius:10px!important}
[data-baseweb="input"] input,[data-baseweb="base-input"] input,[data-baseweb="textarea"] textarea,textarea,
[data-baseweb="select"] input,[data-baseweb="select"] div{color:var(--ink)!important;-webkit-text-fill-color:var(--ink)}
[data-baseweb="input"] input::placeholder,textarea::placeholder,[data-baseweb="select"] input::placeholder{color:#94A3B8!important;-webkit-text-fill-color:#94A3B8}
[data-baseweb="select"] svg{fill:var(--muted)!important}
[data-baseweb="input"]:focus-within,[data-baseweb="textarea"]:focus-within,[data-baseweb="select"]>div:focus-within{border-color:var(--blue)!important;box-shadow:0 0 0 3px rgba(31,111,208,.15)!important}
[data-baseweb="tag"]{background:var(--blue)!important;border-radius:8px!important}
[data-baseweb="tag"],[data-baseweb="tag"] *{color:#FFFFFF!important;-webkit-text-fill-color:#FFFFFF}
[data-baseweb="popover"] :is([role="listbox"],[data-baseweb="menu"]){background:#FFFFFF!important}
[data-baseweb="popover"] li{background:#FFFFFF!important;color:var(--ink)!important}
[data-baseweb="popover"] li *{color:var(--ink)!important}
[data-baseweb="popover"] li:hover,[data-baseweb="popover"] li[aria-selected="true"]{background:#EAF2FD!important}
[data-testid="stCheckbox"] label{cursor:pointer}

/* forms, tables, alerts */
[data-testid="stForm"]{background:var(--card);border:1px solid var(--line)!important;border-radius:16px;padding:1.4rem 1.5rem;box-shadow:0 1px 2px rgba(16,24,40,.04)}
[data-testid="stDataFrame"]{border:1px solid var(--line);border-radius:12px;overflow:hidden}
[data-testid="stAlert"]{border-radius:12px}
.footer{text-align:center;color:#718096!important;font-size:12px;padding:28px 0 8px}

/* tablets */
@media (max-width:900px){
.block-container,[data-testid="stMainBlockContainer"]{padding:3rem 1.1rem 2rem}
[class*="st-key-card"] [data-testid="stHorizontalBlock"]{flex-wrap:wrap;gap:.6rem}
[class*="st-key-card"] [data-testid="stHorizontalBlock"]>:is([data-testid="stColumn"],[data-testid="column"]){flex:1 1 130px!important;min-width:120px!important}
[class*="st-key-card"] [data-testid="stHorizontalBlock"]>:is([data-testid="stColumn"],[data-testid="column"]):first-child{flex:1 1 100%!important}
}
/* phones */
@media (max-width:640px){
.block-container,[data-testid="stMainBlockContainer"]{padding:3rem .75rem 1.5rem}
.page-title{font-size:23px}.page-icon{width:42px;height:42px;font-size:20px}
.hero{padding:18px 18px}.hero-title{font-size:24px}
.stats{grid-template-columns:repeat(2,1fr);gap:10px}
.stat{padding:12px;gap:10px}.stat-icon{width:38px;height:38px;font-size:17px}.stat-value{font-size:22px}
[class*="st-key-card"]{padding:12px 14px}
[class*="st-key-card"] [data-testid="stHorizontalBlock"]>:is([data-testid="stColumn"],[data-testid="column"]){flex:1 1 100%!important}
[data-testid="stForm"]{padding:1rem}
.stDownloadButton button,[data-testid="stDownloadButton"] button{width:100%}
}
</style>"""
md(CSS)

# ----------------------------------------------------------------------------------------
# Sidebar
# ----------------------------------------------------------------------------------------
with st.sidebar:
    md('<div class="brand"><div class="brand-logo">💊</div><div><div class="brand-name">MediCare</div>'
       '<div class="brand-tag">Medicine Reminder</div></div></div>')
    md('<div class="side-label">NAVIGATION</div>')
    page=st.radio("NAVIGATION",["🏠 Dashboard","💊 Medicines","➕ Add Medicine","⏰ Reminders","📊 History & Reports","⚙️ Settings"],
                  label_visibility="collapsed")
    st.markdown("---")
    md(f'<div class="side-date">📅 {today.strftime("%A, %d %B %Y")}</div>')
    md('<div class="side-note">Follow your healthcare professional\'s instructions.</div>')

# ----------------------------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------------------------
if page=="🏠 Dashboard":
    schedule=scheduled(active_meds,history,today)
    taken=sum(x["status"]=="Taken" for x in schedule)
    pending=sum(x["status"]=="Pending" for x in schedule)
    skipped=sum(x["status"]=="Skipped" for x in schedule)
    total=len(schedule)
    hour=datetime.now().hour
    greet="Good morning" if hour<12 else "Good afternoon" if hour<17 else "Good evening"
    now_hm=datetime.now().strftime("%H:%M")
    nxt=next((x for x in schedule if x["status"]=="Pending" and x["time"]>=now_hm),None)
    if not total: sub="No doses scheduled today. Add a medicine to get started."
    elif nxt: sub=f"Next dose at {esc(nxt['time'])} · {esc(nxt['name'])}"
    elif pending: sub=f"{pending} dose(s) still pending from earlier today."
    else: sub="All of today's doses are recorded. Well done!"
    pct=int(round(100*taken/total)) if total else 0
    md(f'<div class="hero"><div class="hero-eyebrow">{today.strftime("%A, %d %B %Y")}</div>'
       f'<div class="hero-title">{greet} 👋</div><div class="hero-sub">{sub}</div>'
       f'<div class="progress"><div class="progress-bar" style="width:{pct}%"></div></div>'
       f'<div class="progress-label">{taken} of {total} doses taken today</div></div>')
    stat_cards([("💊","Active medicines",len(active_meds),"blue"),("📅","Scheduled doses",total,"teal"),
                ("✅","Marked taken",taken,"green"),("⏳","Pending",pending,"amber")])
    left,right=st.columns([1.6,1])
    with left:
        section_title("Today's medication schedule",f"{total} dose(s)" if total else "")
        if not schedule: empty_state("🗓️","Nothing scheduled today","Add a medicine and its reminder times to see them here.")
        for x in schedule:
            with card(f"card_dose_{x['id']}_{x['time']}"):
                a,b,c,d=st.columns([3.2,1.4,1.1,1.1])
                md(dose_info(x),a)
                md(status_pill(x["status"],today,x["time"]),b)
                if x["status"]=="Pending":
                    if c.button("✓ Taken",key=f"dt{x['id']}{x['time']}",type="primary"):
                        mark_dose(x["id"],today.isoformat(),x["time"],"Taken"); st.rerun()
                    if d.button("Skip",key=f"ds{x['id']}{x['time']}"):
                        mark_dose(x["id"],today.isoformat(),x["time"],"Skipped"); st.rerun()
    with right:
        section_title("Dose status")
        if schedule:
            chart=pd.DataFrame([{"Status":s,"Count":sum(x["status"]==s for x in schedule)} for s in ["Taken","Pending","Skipped"]])
            fig=px.pie(chart,names="Status",values="Count",hole=.64,color="Status",
                       color_discrete_map={"Taken":"#16A34A","Pending":"#F59E0B","Skipped":"#DC2626"})
            fig.update_traces(textinfo="value",textfont=dict(color="#FFFFFF",size=13),sort=False)
            fig.update_layout(margin=dict(t=10,b=10,l=10,r=10),height=300,paper_bgcolor="rgba(0,0,0,0)",
                              plot_bgcolor="rgba(0,0,0,0)",font=dict(color="#172B4D",family="Inter, sans-serif"),
                              legend=dict(orientation="h",yanchor="top",y=-0.02,xanchor="center",x=.5,font=dict(color="#172B4D")),
                              annotations=[dict(text=f"<b>{pct}%</b><br>taken",x=.5,y=.5,showarrow=False,
                                                font=dict(size=20,color="#172B4D"))])
            stretch_call(st.plotly_chart,fig,theme=None)
        else:
            empty_state("📈","No data yet","The chart appears once doses are scheduled.")
        md('<div class="callout">ℹ️ This version displays schedules inside the app. Notifications when the app is closed require a separate notification service.</div>')

elif page=="💊 Medicines":
    page_header("💊","Medicines","Search, archive and reactivate your medicine records.")
    if all_meds.empty:
        empty_state("💊","No medicines added yet","Open “Add Medicine” from the sidebar to create your first record.")
    else:
        f1,f2=st.columns([3,1])
        search=f1.text_input("Search by name or dosage",placeholder="Type a name or dosage…")
        filt=f2.selectbox("Show medicines",["All","Active","Archived"])
        view=all_meds.copy()
        if search.strip():
            q=search.strip().lower()
            view=view[view.name.str.lower().str.contains(q,na=False)|view.dosage.str.lower().str.contains(q,na=False)]
        if filt=="Active": view=view[view.active==1]
        if filt=="Archived": view=view[view.active==0]
        section_title("Your medicines",f"{len(view)} shown")
        if view.empty: empty_state("🔍","No matching medicines","Try a different search or filter.")
        for _,m in view.iterrows():
            with card(f"card_med_{int(m['id'])}"):
                a,b,c=st.columns([3,2.2,1.3])
                chips="".join(f'<span class="time-chip">{esc(t.strip())}</span>' for t in str(m["times"]).split(","))
                md(f'<div class="med-name">💊 {esc(m["name"])}</div>'
                   f'<div class="med-meta"><b>Dosage</b>{esc(m["dosage"])}<span class="sep">•</span><b>Frequency</b>{esc(m["frequency"])}</div>'
                   f'<div class="chips">{chips}</div>'
                   f'<div class="med-dates">📅 {esc(m["start_date"])} → {esc(m["end_date"] or "No end date")}</div>',a)
                md(f'<div class="kv"><span>Instructions</span>{esc(m["instructions"] or "—")}</div>'
                   f'<div class="kv"><span>Notes</span>{esc(m["notes"] or "No notes")}</div>',b)
                if int(m["active"]):
                    md('<span class="pill pill-active">● Active</span>',c)
                    if c.button("Archive",key=f"arc{m['id']}"):
                        with connect() as con: con.execute("UPDATE medicines SET active=0 WHERE id=?",(int(m["id"]),)); con.commit()
                        st.rerun()
                else:
                    md('<span class="pill pill-archived">● Archived</span>',c)
                    if c.button("Reactivate",key=f"react{m['id']}",type="primary"):
                        with connect() as con: con.execute("UPDATE medicines SET active=1 WHERE id=?",(int(m["id"]),)); con.commit()
                        st.rerun()

elif page=="➕ Add Medicine":
    page_header("➕","Add Medicine","Enter the schedule provided by your healthcare professional.")
    flash=st.session_state.pop("flash",None)
    if flash: st.success(flash)
    with st.form("add_form",border=True,clear_on_submit=True):
        section_title("Medicine details")
        a,b=st.columns(2)
        name=a.text_input("Medicine name *",placeholder="e.g. Vitamin D")
        dosage=b.text_input("Dosage *",placeholder="e.g. as prescribed")
        frequency=a.selectbox("Frequency",["Once daily","Twice daily","Three times daily","Four times daily","Custom"])
        times=b.multiselect("Scheduled time(s) *",["06:00","07:00","08:00","09:00","12:00","13:00","14:00","17:00","18:00","20:00","21:00","22:00"],default=["08:00"])
        extra=st.text_input("Other times (optional, comma-separated HH:MM)",placeholder="e.g. 08:30, 15:30")
        section_title("Duration")
        a,b=st.columns(2)
        start=a.date_input("Start date",today)
        has_end=b.checkbox("Set end date")
        end=b.date_input("End date",today+timedelta(days=7),disabled=not has_end)
        section_title("Additional information")
        instructions=st.text_input("Instructions (optional)",placeholder="e.g. after food")
        notes=st.text_area("Notes (optional)",height=90)
        submit=st.form_submit_button("💾 Save medicine",type="primary")
        if submit:
            chosen=list(times)
            if extra.strip(): chosen += [x.strip() for x in extra.split(",") if x.strip()]
            valid=[]
            try:
                for tm in chosen:
                    datetime.strptime(tm,"%H:%M")
                    if tm not in valid: valid.append(tm)
            except ValueError:
                st.error("Use valid 24-hour times, e.g. 08:30.")
                valid=[]
            if not name.strip() or not dosage.strip(): st.error("Medicine name and dosage are required.")
            elif not valid: st.error("Select or enter at least one valid time.")
            elif has_end and end<start: st.error("End date cannot be before start date.")
            else:
                add_medicine(name,dosage,frequency,sorted(valid),start,end if has_end else None,instructions,notes)
                st.session_state["flash"]="✅ Medicine saved."
                st.rerun()

elif page=="⏰ Reminders":
    page_header("⏰","Reminders","Review scheduled doses and record what happened.")
    d1,_sp=st.columns([1,2])
    day=d1.date_input("Choose date",today,key="reminder_date")
    schedule=scheduled(active_meds,logs(),day)
    r_taken=sum(x["status"]=="Taken" for x in schedule)
    r_skip=sum(x["status"]=="Skipped" for x in schedule)
    r_pend=sum(x["status"]=="Pending" for x in schedule)
    stat_cards([("📅","Scheduled",len(schedule),"blue"),("✅","Taken",r_taken,"green"),
                ("⏭️","Skipped",r_skip,"red"),("⏳","Pending",r_pend,"amber")])
    section_title("Doses",day.strftime("%A, %d %B %Y"))
    if not schedule: empty_state("🗓️","No doses scheduled","Nothing is scheduled for this date.")
    for x in schedule:
        with card(f"card_rem_{x['id']}_{x['time']}"):
            a,b,c,d=st.columns([3.2,1.4,1.5,1.5])
            md(dose_info(x),a)
            md(status_pill(x["status"],day,x["time"]),b)
            if x["status"]=="Pending":
                if c.button("✓ Mark taken",key=f"rt{x['id']}{day}{x['time']}",type="primary"):
                    mark_dose(x["id"],day.isoformat(),x["time"],"Taken"); st.rerun()
                if d.button("Mark skipped",key=f"rs{x['id']}{day}{x['time']}"):
                    mark_dose(x["id"],day.isoformat(),x["time"],"Skipped"); st.rerun()
            elif c.button("↺ Reset status",key=f"rr{x['id']}{day}{x['time']}"):
                with connect() as con:
                    con.execute("DELETE FROM dose_logs WHERE medicine_id=? AND scheduled_date=? AND scheduled_time=?",(x["id"],day.isoformat(),x["time"])); con.commit()
                st.rerun()

elif page=="📊 History & Reports":
    page_header("📊","History & Reports","Browse past doses, export them and see the summary.")
    data=logs()
    if data.empty: empty_state("📊","No history yet","Dose history appears after you mark doses as taken or skipped.")
    else:
        a,b=st.columns(2)
        start=a.date_input("From date",today-timedelta(days=30))
        end=b.date_input("To date",today)
        data["scheduled_date"]=pd.to_datetime(data["scheduled_date"],errors="coerce")
        view=data[(data.scheduled_date.dt.date>=start)&(data.scheduled_date.dt.date<=end)].copy()
        n_taken=int((view.status=="Taken").sum()); n_skip=int((view.status=="Skipped").sum())
        stat_cards([("🧾","Recorded doses",len(view),"blue"),("✅","Taken",n_taken,"green"),("⏭️","Skipped",n_skip,"red")])
        section_title("Dose log",f"{len(view)} record(s)")
        if view.empty:
            empty_state("🔍","No records in this range","Choose a wider date range.")
        else:
            shown=view[["scheduled_date","scheduled_time","medicine_name","dosage","status","recorded_at"]].rename(columns={
                "scheduled_date":"Date","scheduled_time":"Scheduled time","medicine_name":"Medicine","dosage":"Dosage","status":"Status","recorded_at":"Recorded at"})
            shown["Date"]=shown["Date"].dt.strftime("%d %b %Y")
            shown["Status"]=shown["Status"].map({"Taken":"✅ Taken","Skipped":"⏭️ Skipped"}).fillna(shown["Status"])
            stretch_call(st.dataframe,shown,hide_index=True)
            st.download_button("⬇️ Export history (CSV)",view.to_csv(index=False).encode("utf-8"),"medicare_dose_history.csv","text/csv")
            section_title("Summary chart")
            summary=view.groupby("status",as_index=False).size().rename(columns={"size":"Count"})
            fig=px.bar(summary,x="status",y="Count",color="status",text="Count",color_discrete_map={"Taken":"#16A34A","Skipped":"#DC2626"})
            fig.update_traces(textposition="outside",cliponaxis=False,textfont=dict(color="#172B4D"))
            fig.update_layout(showlegend=False,paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",height=340,
                              margin=dict(t=20,b=10,l=10,r=10),font=dict(color="#172B4D",family="Inter, sans-serif"),
                              xaxis=dict(title=None,tickfont=dict(color="#172B4D")),
                              yaxis=dict(title=None,gridcolor="#E2E8F0",tickformat="d",tickfont=dict(color="#172B4D")))
            stretch_call(st.plotly_chart,fig,theme=None)

elif page=="⚙️ Settings":
    page_header("⚙️","Settings","About the app and where your data lives.")
    archived=len(all_meds)-len(active_meds)
    stat_cards([("💊","Total medicines",len(all_meds),"blue"),("✅","Active",len(active_meds),"green"),
                ("🗄️","Archived",archived,"amber"),("🧾","Dose records",len(history),"teal")])
    section_title("About MediCare")
    md('<div class="info-grid">'
       '<div class="info-card"><h4>📘 About</h4><p>A local medicine schedule and dose-tracking mini-project built with Python, Streamlit, and SQLite.</p></div>'
       f'<div class="info-card"><h4>💾 Storage</h4><p>Database file: <code>{esc(DB.name)}</code><br>Data is stored locally. Back up medicare.db to preserve your records.</p></div>'
       '</div>')
    md('<div class="callout warn">⚠️ This app is for reminders and record-keeping only. It does not prescribe medicines or recommend dosage changes. Follow professional instructions and seek qualified advice if a dose is missed.</div>')

md("<div class='footer'>MediCare · Medicine Reminder System · Python + Streamlit + SQLite</div>")
