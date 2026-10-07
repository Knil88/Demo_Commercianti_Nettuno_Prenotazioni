import base64
import hashlib
import hmac
import html
import os
import secrets
import sys
import textwrap
import time
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from database import (
    BASE_DIR,
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USERNAME,
    GIORNI,
    UPLOAD_DIR,
    add_assenza,
    add_prenotazione,
    add_servizio,
    add_staff,
    cancella_prenotazione,
    get_assenze,
    get_impostazioni,
    get_membro,
    get_prenotazione,
    get_prenotazioni,
    get_servizio,
    get_servizi,
    get_slot_disponibili,
    get_staff,
    get_staff_orari,
    get_statistiche,
    hash_password,
    init_db,
    remove_assenza,
    set_staff_credenziali,
    set_staff_orari,
    slot_occupato,
    update_impostazioni,
    update_prenotazione_staff,
    update_servizio,
    update_staff,
    update_stato_prenotazione,
    verify_admin,
    verify_staff,
)
from email_utils import invia_email, notifica_nuova_prenotazione, smtp_configurato

init_db()


def _secrets():
    try:
        return st.secrets
    except Exception:
        return {}


def load_impostazioni():
    imp = dict(get_impostazioni())
    sec = _secrets()
    smtp = {}
    try:
        smtp = dict(sec.get("smtp", {}) or {})
    except Exception:
        smtp = {}
    if smtp.get("host"):
        imp["smtp_host"] = smtp.get("host")
    if smtp.get("port"):
        imp["smtp_port"] = int(smtp.get("port"))
    if smtp.get("user"):
        imp["smtp_user"] = smtp.get("user")
    if smtp.get("password"):
        imp["smtp_password"] = smtp.get("password")
    if smtp.get("to"):
        imp["email"] = smtp.get("to")
    logo = (imp.get("logo_path") or "").replace("\\", "/")
    if logo:
        imp["logo_path"] = logo
    return imp


def _page_icon():
    path = (get_impostazioni().get("logo_path") or "").replace("\\", "/")
    real = os.path.join(BASE_DIR, path) if path else ""
    if real and os.path.isfile(real):
        return real
    emblem = os.path.join(BASE_DIR, "uploads", "logo_nettuno_emblema.jpg")
    if os.path.isfile(emblem):
        return emblem
    return "✂️"


AUTH_COOKIE = "nettuno_auth"
AUTH_DAYS = 14

# Voci di menu: costanti perché la stringa va confrontata in più punti.
# Con gli emoji inline un refactor cambiava la rotta e la pagina restava vuota.
MENU_HOME = "🏠 Home"
MENU_PRENOTA = "📅 Prenota"
MENU_GESTIONE = "📋 Gestione"
MENU_CONFIGURA = "⚙ Configura"
MENU_ESCI = "🚪 Esci"
MENU_AREA = "🔐 Area riservata"
MENU_APPUNTAMENTI = "👤 I miei appuntamenti"
def _cookie_header():
    try:
        return st.context.headers.get("Cookie") or ""
    except Exception:
        return ""


_boot = get_impostazioni()
st.set_page_config(
    page_title=f"{_boot.get('nome_attivita') or 'Prenota'} · Prenota online",
    page_icon=_page_icon(),
    layout="wide",
    # La navigazione è in alto: la sidebar resta chiusa anche per l'admin.
    initial_sidebar_state="collapsed",
    menu_items={"Get help": None, "Report a bug": None, "About": None},
)

impostazioni = load_impostazioni()
primario = impostazioni.get("colore_primario") or "#1E3A5F"
secondario = impostazioni.get("colore_secondario") or "#E94560"

# False durante lo sviluppo per rivedere Rerun, impostazioni e tema di Streamlit.
NASCONDI_TOOLBAR = True

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "ruolo" not in st.session_state:
    st.session_state.ruolo = None
if "staff_id" not in st.session_state:
    st.session_state.staff_id = None
if "servizio_selezionato" not in st.session_state:
    st.session_state.servizio_selezionato = None
if "prenotazione_ok" not in st.session_state:
    st.session_state.prenotazione_ok = None
if "staff_selezionato" not in st.session_state:
    st.session_state.staff_selezionato = None


def _auth_secret():
    try:
        sec = _secrets()
        key = sec.get("cookie_key")
        if not key:
            admin = dict(sec.get("admin", {}) or {})
            key = admin.get("password")
        if key:
            return str(key)
    except Exception:
        pass
    path = os.path.join(BASE_DIR, ".auth_secret")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as handle:
            saved = handle.read().strip()
            if saved:
                return saved
    generated = secrets.token_hex(32)
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(generated)
    except OSError:
        pass
    return generated


def _sign_token(ruolo, staff_id, exp):
    payload = f"{ruolo}|{int(staff_id or 0)}|{int(exp)}"
    sig = hmac.new(_auth_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}|{sig}"


def _parse_token(token):
    try:
        ruolo, sid, exp, sig = (token or "").split("|", 3)
        exp = int(exp)
        if exp < int(time.time()):
            return None
        atteso = _sign_token(ruolo, sid, exp)
        if not hmac.compare_digest(atteso, f"{ruolo}|{sid}|{exp}|{sig}"):
            return None
        if ruolo == "admin":
            return {"ruolo": "admin", "staff_id": None}
        if ruolo == "staff":
            return {"ruolo": "staff", "staff_id": int(sid)}
    except Exception:
        return None
    return None


def _leggi_auth_cookie():
    raw = _cookie_header()
    for pezzo in raw.split(";"):
        pezzo = pezzo.strip()
        if pezzo.startswith(AUTH_COOKIE + "="):
            return pezzo.split("=", 1)[1].strip()
    return ""


def _html_script(markup, **kwargs):
    """st.iframe sostituisce components.html dal 1.65; il fallback copre versioni vecchie."""
    if hasattr(st, "iframe"):
        # st.iframe rifiuta width/height 0: 1px resta invisibile come il vecchio 0.
        st.iframe(markup, **{k: (1 if v == 0 else v) for k, v in kwargs.items()})
    else:
        components.html(markup, **kwargs)


def _js_set_cookie(valore, giorni=AUTH_DAYS):
    _html_script(
        "<script>"
        f"document.cookie='{AUTH_COOKIE}='+encodeURIComponent('{valore}')+"
        f"';max-age={int(giorni)*86400};path=/;SameSite=Lax';"
        "</script>",
        height=0,
        width=0,
    )


def _js_clear_cookie():
    _html_script(
        f"<script>document.cookie='{AUTH_COOKIE}=;max-age=0;path=/;SameSite=Lax';</script>",
        height=0,
        width=0,
    )


def _ripristina_login_da_cookie():
    if st.session_state.get("logged_in"):
        return
    token = _leggi_auth_cookie()
    dati = _parse_token(token)
    if not dati:
        return
    if dati["ruolo"] == "admin":
        st.session_state.logged_in = True
        st.session_state.ruolo = "admin"
        st.session_state.staff_id = None
        return
    membro = get_membro(dati["staff_id"]) if dati.get("staff_id") else None
    if not membro or not membro.get("attivo"):
        return
    st.session_state.logged_in = True
    st.session_state.ruolo = "staff"
    st.session_state.staff_id = membro["id"]


def _sync_auth_cookie():
    if st.session_state.get("_pending_logout"):
        _js_clear_cookie()
        st.session_state.logged_in = False
        st.session_state.ruolo = None
        st.session_state.staff_id = None
        st.session_state._pending_logout = False
        st.session_state._cookie_sent = False
        st.session_state._next_menu = MENU_PRENOTA
        return
    _ripristina_login_da_cookie()
    if st.session_state.get("logged_in") and not st.session_state.get("_cookie_sent"):
        exp = int(time.time()) + AUTH_DAYS * 86400
        token = _sign_token(st.session_state.ruolo, st.session_state.staff_id, exp)
        _js_set_cookie(token)
        st.session_state._cookie_sent = True


def esc(value):
    return html.escape("" if value is None else str(value))


def html_md(markup):
    """HTML in Streamlit markdown: niente indentazione, altrimenti diventa un code block."""
    cleaned = "\n".join(line.strip() for line in textwrap.dedent(str(markup)).splitlines()).strip()
    st.markdown(cleaned, unsafe_allow_html=True)


def resolve_logo(path):
    if not path:
        return None
    path = str(path).replace("\\", "/")
    if os.path.isabs(path) and os.path.isfile(path):
        return path
    relative = os.path.join(BASE_DIR, *path.split("/"))
    if os.path.isfile(relative):
        return relative
    return None


def logo_data_uri(path):
    real = resolve_logo(path)
    if not real:
        return None
    ext = os.path.splitext(real)[1].lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "image/png")
    with open(real, "rb") as handle:
        payload = base64.b64encode(handle.read()).decode()
    return f"data:{mime};base64,{payload}"


def _css_html(markup):
    """Inietta il CSS togliendo le righe vuote e vigilando sugli asterischi.

    Il CSS passa dal pipeline markdown di Streamlit, che ha due manie:
    - una riga vuota chiude il blocco HTML, e il CSS dopo verrebbe stampato
      come testo visibile sopra la pagina;
    - due asterischi vengono letti come apertura/chiusura di emphasis, e il
      '*/' risultante inietta un </style> a meta' spaccando il foglio di stile.
      Per questo nel CSS c'e' un solo '*', il reset box-sizing: aggiungerne un
      secondo (per esempio '*::before' o un selettore '.pad *') rompe tutto.
    """
    testo = str(markup)
    if testo.count("*") > 1:
        print(
            f"ATTENZIONE: {testo.count('*')} asterischi nel CSS. "
            "Tieni il CSS a un solo '*' (reset box-sizing), altrimenti si spacca.",
            file=sys.stderr,
        )
    html_md("\n".join(riga for riga in testo.splitlines() if riga.strip()))


def inject_css(cambio_sezione=True):
    # Il blocco <style> va re-iniettato a ogni rerun: Streamlit rimuove dalla
    # DOM gli elementi che il run precedente non ri-emette, quindi skippare
    # l'iniezione dopo il primo render cancella lo stile (logo e header gianti).
    # Non provare a "ottimizzarlo" con una firma in session_state: non funziona.

    # Dentro <style> niente commenti CSS: il pipeline markdown di Streamlit
    # tratta '*' come emphasis e inietta un </style> a meta', riversando il
    # CSS come testo. Va iniettato con st.markdown, non st.html: DOMPurify
    # svuota lo <style>.
    css_toolbar = (
        '[data-testid="stToolbar"], [data-testid="stHeaderActionElements"], '
        '[data-testid="stStatusWidget"] { display: none !important; }\n'
        '[data-testid="stHeader"] { background: transparent !important; '
        "height: 0 !important; min-height: 0 !important; }"
        if NASCONDI_TOOLBAR
        else ""
    )
    # Stessa sezione, rerun interno (scegliere un servizio, cambiare un filtro):
    # niente animazioni, altrimenti ripartono da capo a ogni interazione.
    # Elenco esplicito, niente '*': vedi la regola sugli asterischi in _css_html.
    css_fermo = (
        ""
        if cambio_sezione
        else ".header, .metric-card, .booking-item, .section-title::after "
        "{ animation: none !important; transition: none !important; }"
    )
    _css_html(
        f"""
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Playfair+Display:ital,wght@0,500;0,600;0,700;1,500&display=swap');
* {{ box-sizing: border-box; }}
:root, .stApp {{
    --rag-xl: 26px;
    --rag-lg: 20px;
    --rag-md: 14px;
    --rag-pill: 999px;
    --ombra-sm: 0 4px 14px rgba(30,58,95,.07);
    --ombra-md: 0 10px 30px rgba(30,58,95,.11);
    --ombra-lg: 0 18px 46px rgba(30,58,95,.17);
    --ink: #2A3242;
    --muted: #6E7686;
    --hairline: #ECE6EC;
}}
.stApp {{
    background-color: #F8F5F7;
    background-image:
        radial-gradient(circle at 10% 6%, rgba(233,69,96,.055), transparent 44%),
        radial-gradient(circle at 92% 2%, rgba(30,58,95,.06), transparent 40%);
    background-attachment: fixed;
    font-family: 'Inter', sans-serif;
    color: var(--ink);
}}
.block-container {{ padding-top: 1.5rem; max-width: 1060px; padding-bottom: 3rem; }}
.st-key-topnav {{ margin-bottom: 1.1rem; }}
.st-key-topnav .stButton > button {{
    background: #fff; color: var(--ink); border: 1px solid var(--hairline);
    border-radius: var(--rag-pill); padding: 0.5rem 1rem; font-weight: 600;
    box-shadow: var(--ombra-sm); transition: all .2s ease;
}}
.st-key-topnav .stButton > button:hover {{
    border-color: {secondario}; color: {primario};
    transform: translateY(-1px); box-shadow: var(--ombra-md);
}}
.st-key-topnav button[data-testid="stBaseButton-primary"] {{
    background: linear-gradient(135deg, {primario}, {secondario});
    color: #fff; border: none; box-shadow: 0 8px 20px rgba(30,58,95,.22);
}}
.st-key-topnav button[data-testid="stBaseButton-primary"]:hover {{
    color: #fff; transform: translateY(-1px); box-shadow: 0 12px 26px rgba(30,58,95,.30);
}}
section[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, #FFFFFF 0%, #FCF8FA 100%);
    border-right: 1px solid var(--hairline);
    display: none !important;
}}
[data-testid="stExpandSidebarButton"] {{ display: none !important; }}
@keyframes fadeInUp {{ from {{ opacity: 0; transform: translateY(20px); }} to {{ opacity: 1; transform: translateY(0); }} }}
@keyframes fadeInDown {{ from {{ opacity: 0; transform: translateY(-20px); }} to {{ opacity: 1; transform: translateY(0); }} }}
@keyframes slideInLeft {{ from {{ opacity: 0; transform: translateX(-16px); }} to {{ opacity: 1; transform: translateX(0); }} }}
@keyframes expandLine {{ to {{ width: 100%; }} }}
{css_fermo}
.header {{
    background: linear-gradient(135deg, {primario}, {secondario});
    padding: 2.2rem 1.6rem; border-radius: var(--rag-xl); color: #fff; text-align: center;
    margin-bottom: 1.6rem; box-shadow: var(--ombra-lg);
    animation: fadeInDown 0.3s ease-out;
    position: relative; overflow: hidden;
}}
.header::after {{
    content: ''; position: absolute; inset: 0; pointer-events: none;
    background: linear-gradient(180deg, rgba(255,255,255,.20), rgba(255,255,255,0) 58%);
}}
.header img {{
    width: 96px; height: 96px; object-fit: cover; border-radius: 50%; margin-bottom: 0.75rem;
    border: 3px solid rgba(255,255,255,.85); box-shadow: 0 10px 26px rgba(0,0,0,.24);
    position: relative; z-index: 1;
}}
.header h1 {{
    font-family: 'Playfair Display', serif; font-size: 2.35rem; font-weight: 700;
    margin: 0; color: #fff; letter-spacing: -.01em; position: relative; z-index: 1;
}}
.header p {{
    margin: 0.45rem 0 0; opacity: .94; font-size: 0.97rem; color: #fff;
    position: relative; z-index: 1;
}}
.header.has-foto {{ padding: 0; }}
.header.has-foto::after {{ display: none; }}
.header .header-photo {{
    position: absolute; inset: 0; z-index: 0;
    background-size: cover; background-position: center;
}}
.header .header-veil {{
    position: absolute; inset: 0; z-index: 0;
    background: linear-gradient(180deg, rgba(0,0,0,.12), rgba(0,0,0,.26));
}}
.header .fascia {{
    position: relative; z-index: 1; width: 100%; margin: 3.4rem 0;
    background: rgba(18,22,32,.58);
    border-top: 1px solid rgba(255,255,255,.22);
    border-bottom: 1px solid rgba(255,255,255,.22);
    padding: 1.05rem 1.2rem;
}}
.header .fascia-dentro {{
    position: relative; z-index: 1; max-width: 660px; margin: 0 auto; text-align: center;
}}
.steps {{
    display: flex; align-items: center; justify-content: center; flex-wrap: wrap;
    gap: 0.15rem; background: #fff; border: 1px solid var(--hairline);
    border-radius: var(--rag-pill); padding: 0.45rem 0.8rem; margin-bottom: 1.6rem;
    box-shadow: var(--ombra-sm);
}}
.step {{ display: flex; align-items: center; gap: 0.5rem; padding: 0.2rem 0.6rem; border-radius: var(--rag-pill); }}
.step .num {{
    width: 26px; height: 26px; border-radius: 50%; flex: none;
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 0.76rem; font-weight: 700; background: #F2EDF1; color: var(--muted);
}}
.step .txt {{ font-size: 0.83rem; color: var(--muted); white-space: nowrap; }}
.step.done .num {{ background: rgba(39,174,96,.16); color: #1d7a45; }}
.step.done .txt {{ color: #4a5563; }}
.step.active {{ background: linear-gradient(135deg, {primario}, {secondario}); box-shadow: 0 6px 16px rgba(30,58,95,.20); }}
.step.active .num {{ background: rgba(255,255,255,.24); color: #fff; }}
.step.active .txt {{ color: #fff; font-weight: 600; }}
.step-sep {{ color: #DCD2DA; font-size: 0.75rem; }}
.metric-card {{
    background: #fff; padding: 1.2rem 0.7rem 1.1rem;
    border-radius: var(--rag-lg); box-shadow: var(--ombra-sm);
    text-align: center; border-top: 4px solid {primario};
    animation: fadeInUp 0.25s ease-out both;
    min-height: 152px; height: 100%;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
}}
.metric-icon {{ font-size: 1.4rem; color: {secondario}; margin-bottom: 0.45rem; line-height: 1; }}
.metric-value {{
    font-family: 'Playfair Display', serif;
    font-size: 1.95rem; font-weight: 700; color: {primario};
    line-height: 1.1; white-space: nowrap; letter-spacing: -.01em;
}}
.metric-label {{ color: var(--muted); font-size: 0.78rem; margin-top: 0.35rem; line-height: 1.25; }}
{css_toolbar}
.card, .booking-item, .service-pick, .recap-box, .staff-pick {{
    background: #fff; border: 1px solid var(--hairline); border-radius: var(--rag-lg);
    padding: 1.3rem 1.5rem; margin-bottom: 0.7rem; box-shadow: var(--ombra-sm);
    transition: box-shadow .25s ease, transform .25s ease;
}}
.booking-item {{ border-left: 4px solid {secondario}; animation: slideInLeft 0.25s ease-out both; }}
.booking-item.confermato, .booking-item.confermata {{ border-left-color: #27ae60; }}
.booking-item.pagato {{ border-left-color: #1a7f9e; }}
.booking-item.in_attesa {{ border-left-color: #f39c12; }}
.booking-item.annullata {{ border-left-color: #95a5a6; opacity: 0.7; }}
.status-badge {{
    display: inline-block; padding: 0.28rem 0.85rem; border-radius: var(--rag-pill);
    font-size: 0.78rem; font-weight: 600; letter-spacing: .01em;
}}
.status-confermato, .status-confermata {{ background: #d4edda; color: #155724; }}
.status-pagato {{ background: #d6eef6; color: #0c5460; }}
.status-in_attesa {{ background: #fff3cd; color: #856404; }}
.status-annullata {{ background: #e8e4e9; color: #4a4a52; }}
.section-title {{
    font-family: 'Playfair Display', serif;
    font-size: 1.6rem; font-weight: 600; color: {primario};
    border-bottom: 3px solid {primario}; padding-bottom: 0.5rem; margin-bottom: 1.2rem;
    position: relative; display: inline-block;
}}
.section-title::after {{
    content: ''; position: absolute; bottom: -3px; left: 0; width: 0; height: 3px;
    background: {secondario}; animation: expandLine 0.4s ease-out 0.1s forwards;
}}
.empty-state {{ text-align: center; padding: 3rem; color: var(--muted); }}
.empty-state i {{ font-size: 3rem; margin-bottom: 1rem; display: block; color: {primario}; }}
.service-pick {{
    border-left: 4px solid {primario}; position: relative;
    min-height: 178px; height: 100%;
}}
.service-pick:hover, .staff-pick:hover {{ transform: translateY(-2px); box-shadow: var(--ombra-md); }}
.service-pick.selected {{
    border-left-color: {secondario}; transform: translateY(-2px);
    box-shadow: var(--ombra-md), inset 0 0 0 2px {secondario};
}}
.service-pick.selected::before, .staff-pick.selected::before {{
    content: '\\f00c'; font-family: 'Font Awesome 6 Free'; font-weight: 900;
    position: absolute; top: 14px; right: 16px; width: 26px; height: 26px;
    border-radius: 50%; background: {secondario}; color: #fff;
    display: flex; align-items: center; justify-content: center; font-size: 0.68rem;
}}
.service-pick h3 {{
    font-family: 'Playfair Display', serif;
    margin: 0 0 0.45rem; color: {primario}; font-size: 1.45rem; line-height: 1.25;
    word-break: normal; overflow-wrap: break-word; hyphens: none;
}}
.service-pick p {{ color: #555; font-size: 0.95rem; margin: 0 0 0.85rem; min-height: 2.6em; }}
.service-pick strong {{ color: {primario}; font-size: 1rem; }}
.recap-box {{ border-left: 4px solid {primario}; background: linear-gradient(135deg, #fff, #FDF7F9); }}
.staff-pick {{
    border-left: 4px solid {primario}; position: relative;
    text-align: center; min-height: 215px;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
}}
.staff-pick.selected {{
    border-left-color: {secondario}; transform: translateY(-2px);
    box-shadow: var(--ombra-md), inset 0 0 0 2px {secondario};
}}
.staff-pick.offline {{ opacity: 0.5; }}
.staff-pick img {{
    width: 90px; height: 90px; border-radius: 50%; object-fit: cover;
    margin: 0 auto 0.65rem; display: block; background: #eee;
    border: 2px solid #fff; box-shadow: 0 6px 18px rgba(30,58,95,.16);
}}
.staff-pick h3 {{ font-family: 'Playfair Display', serif; margin: 0.2rem 0 0.15rem; color: {primario}; font-size: 1.15rem; }}
.staff-pick p {{ color: var(--muted); font-size: 0.85rem; margin: 0; }}
.stButton > button {{ border-radius: var(--rag-md); font-weight: 600; }}
button[data-testid="stBaseButton-primary"] {{
    background: linear-gradient(135deg, {primario}, {secondario});
    border: none; border-radius: var(--rag-md); color: #fff;
    box-shadow: 0 8px 20px rgba(30,58,95,.18);
}}
button[data-testid="stBaseButton-primary"]:hover {{ box-shadow: 0 12px 26px rgba(30,58,95,.28); }}
.product-foot {{
    text-align: center; color: var(--muted); font-size: 0.78rem; letter-spacing: .04em;
    margin-top: 2.6rem; padding: 0.8rem 1rem; border-radius: var(--rag-pill);
    background: rgba(255,255,255,.72); border: 1px solid var(--hairline);
}}
@media (max-width: 768px) {{
    .block-container {{ padding: 1rem .9rem 2.5rem; }}
    .header {{ padding: 1.5rem 1rem; border-radius: var(--rag-lg); margin-bottom: 1.2rem; }}
    .header img {{ width: 66px; height: 66px; margin-bottom: 0.45rem; border-width: 2px; }}
    .header h1 {{ font-size: 1.55rem; }}
    .header p {{ font-size: 0.84rem; margin: 0.28rem 0 0; }}
    .header .fascia {{ margin: 2rem 0; padding: .75rem .85rem; }}
    .header .fascia-dentro {{ max-width: 100%; }}
    .steps {{ padding: 0.35rem 0.45rem; margin-bottom: 1.2rem; }}
    .step {{ padding: 0.15rem 0.3rem; gap: 0.3rem; }}
    .step .num {{ width: 22px; height: 22px; font-size: 0.66rem; }}
    .step .txt {{ font-size: 0.68rem; }}
    .section-title {{ font-size: 1.3rem; }}
    .card, .booking-item, .service-pick, .recap-box, .staff-pick {{ padding: 1rem 1.05rem; }}
    .service-pick h3 {{ font-size: 1.2rem; }}
    .staff-pick img {{ width: 72px; height: 72px; }}
    .service-pick, .staff-pick {{ min-height: auto; }}
    .staff-pick {{ padding-top: 1.4rem; }}
    .metric-card {{ min-height: 112px; padding: 1rem .5rem .9rem; }}
    .metric-value {{ font-size: 1.5rem; }}
    .product-foot {{ font-size: 0.7rem; margin-top: 1.8rem; padding: 0.6rem 0.7rem; }}
    .stButton > button, .st-key-topnav .stButton > button,
    .stDownloadButton > button, .stFormSubmitButton > button {{ min-height: 46px; }}
    .stTextInput input, .stTextArea textarea, .stNumberInput input {{ font-size: 16px; }}
.st-key-topnav {{ margin-bottom: 0.8rem; }}
</style>
"""
    )


def render_header(subtitle=None):
    nome = esc(impostazioni.get("nome_attivita") or "La Mia Attività")
    indirizzo = esc(impostazioni.get("indirizzo") or "")
    telefono = esc(impostazioni.get("telefono") or "")
    email = esc(impostazioni.get("email") or "")
    uri = logo_data_uri(impostazioni.get("logo_path") or "")
    sfondo = logo_data_uri(impostazioni.get("sfondo_header") or "")
    logo_html = (
        f'<img src="{uri}" alt="Logo" />'
        if uri
        else '<div style="font-size:3rem;margin-bottom:0.4rem;"><i class="fas fa-calendar-check"></i></div>'
    )
    parts = [f'<div class="header{" has-foto" if sfondo else ""}">']
    if sfondo:
        parts.append(
            f'<div class="header-photo" style="background-image:url(\'{sfondo}\');"></div>'
            f'<div class="header-veil"></div>'
        )
    parti_testo = [logo_html, f"<h1>{nome}</h1>"]
    if indirizzo:
        parti_testo.append(f'<p><i class="fas fa-map-marker-alt"></i> {indirizzo}</p>')
    if telefono:
        parti_testo.append(f'<p><i class="fas fa-phone"></i> {telefono}</p>')
    if email:
        parti_testo.append(f'<p><i class="fas fa-envelope"></i> {email}</p>')
    if subtitle:
        parti_testo.append(f"<p>{esc(subtitle)}</p>")
    if sfondo:
        # Con foto il testo va su una fascia orizzontale semitrasparente:
        # si vede la foto sopra e sotto, ma il nome resta leggibile.
        parti_testo.insert(0, '<div class="fascia"><div class="fascia-dentro">')
        parti_testo.append("</div></div>")
    parts.append("".join(parti_testo))
    parts.append("</div>")
    html_md("".join(parts))


def _scrolla(ancora):
    """Porta in vista un blocco appena comparso.

    Non scrolliamo a inizio pagina sui rerun interni (farebbe perdere il posto
    nella lista dei servizi): scrolliamo invece al blocco che e' appena comparso,
    cosi' l'utente non deve cercarlo a mano.
    Attenzione: st.html esegue solo il JavaScript racchiuso in <script>, se no
    lo stampa come testo.
    """
    if not ancora:
        return
    st.html(
        f"<script>document.getElementById({ancora!r})"
        "?.scrollIntoView({behavior: 'smooth', block: 'start'});</script>",
        unsafe_allow_javascript=True,
    )


def _scrolla_in_cima():
    st.html(
        "<script>window.scrollTo({top: 0, behavior: 'smooth'});</script>",
        unsafe_allow_javascript=True,
    )


def render_steps(passo_attivo):
    """Barra di progressi a 3 passi: tratto grafico distintivo di questa app."""
    passi = ["Servizio", "Chi ti segue", "Giorno e ora"]
    frammenti = []
    for idx, label in enumerate(passi, start=1):
        if idx < passo_attivo:
            stato, segno = "done", '<i class="fas fa-check"></i>'
        elif idx == passo_attivo:
            stato, segno = "active", str(idx)
        else:
            stato, segno = "", str(idx)
        frammenti.append(
            f'<div class="step {stato}"><span class="num">{segno}</span>'
            f'<span class="txt">{esc(label)}</span></div>'
        )
        if idx < len(passi):
            frammenti.append('<span class="step-sep">&bull;</span>')
    html_md(f'<div class="steps">{"".join(frammenti)}</div>')


def _calcola_passo():
    if not st.session_state.servizio_selezionato:
        return 1
    if get_staff() and not is_operatore() and not st.session_state.staff_selezionato:
        return 2
    return 3


def is_admin():
    return st.session_state.get("logged_in") and st.session_state.get("ruolo") == "admin"


def is_operatore():
    return st.session_state.get("logged_in") and st.session_state.get("ruolo") == "staff"


def _dettagli_nav():
    """Riga sotto la nav: ruolo e orari, che prima stavano in sidebar."""
    if is_admin():
        nota = "Accesso: titolare"
    elif is_operatore():
        membro = get_membro(st.session_state.staff_id) if st.session_state.staff_id else None
        nota = f"Operatore: {membro['nome'] if membro else 'staff'}"
    else:
        nota = "Prenota come cliente · lo staff conferma l'appuntamento"
    if is_admin() and not smtp_configurato(impostazioni):
        nota += " · email non configurata"
    orari = (
        f"{impostazioni.get('orario_apertura') or '09:00'}–{impostazioni.get('orario_chiusura') or '19:00'}"
    )
    pausa_i = (impostazioni.get("pausa_inizio") or "").strip()
    pausa_f = (impostazioni.get("pausa_fine") or "").strip()
    if pausa_i and pausa_f:
        orari += f" · pausa {pausa_i}–{pausa_f}"
    st.caption(f"{nota} · Orari {orari}")


def _opzioni_menu():
    if is_admin():
        return [MENU_HOME, MENU_PRENOTA, MENU_GESTIONE, MENU_CONFIGURA, MENU_ESCI]
    if is_operatore():
        return [MENU_APPUNTAMENTI, MENU_PRENOTA, MENU_ESCI]
    return [MENU_PRENOTA, MENU_AREA]


def _prepara_menu():
    """Normalizza la sezione senza renderizzare: serve per iniettare il CSS per primo."""
    opzioni = _opzioni_menu()
    prossimo = st.session_state.pop("_next_menu", None)
    if prossimo in opzioni:
        st.session_state.menu = prossimo
    elif st.session_state.get("menu") not in opzioni:
        st.session_state.menu = opzioni[0]
    return opzioni


def topnav_setup(opzioni):
    """Nav in alto per tutti i ruoli: su telefono la sidebar nascosta è un vicolo cieco."""
    with st.container(key="topnav"):
        cols = st.columns(len(opzioni), gap="small")
        for col, label in zip(cols, opzioni):
            with col:
                attiva = st.session_state.menu == label
                if st.button(
                    label,
                    key=f"topnav::{label}",
                    width="stretch",
                    type="primary" if attiva else "secondary",
                ):
                    st.session_state.menu = label
                    st.rerun()
    _dettagli_nav()
    return st.session_state.menu


def _login_ok(username, password):
    try:
        admin = dict(_secrets().get("admin", {}) or {})
        su, sp = admin.get("username"), admin.get("password")
        if su and sp and username.strip() == str(su).strip() and password == str(sp):
            return {"ruolo": "admin"}
    except Exception:
        pass
    if verify_admin(username, password):
        return {"ruolo": "admin"}
    membro = verify_staff(username, password)
    if membro:
        if not membro.get("attivo"):
            return {"errore": "Questo account non è in servizio. Chiedi al titolare."}
        return {"ruolo": "staff", "staff": membro}
    return None


def pagina_login():
    render_header("Area riservata")
    st.markdown('<h2 class="section-title"><i class="fas fa-lock"></i> Accedi</h2>', unsafe_allow_html=True)
    st.write("Il titolare vede tutto il salone. Ogni operatore vede **solo i suoi** appuntamenti.")
    with st.form("login_form"):
        username = st.text_input("Utente")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Entra", width='stretch', type="primary")
    if submitted:
        esito = _login_ok(username, password)
        if esito and esito.get("errore"):
            st.error(esito["errore"])
        elif esito and esito.get("ruolo") == "admin":
            st.session_state.logged_in = True
            st.session_state.ruolo = "admin"
            st.session_state.staff_id = None
            st.session_state._next_menu = MENU_HOME
            st.toast("Accesso titolare")
            st.rerun()
        elif esito and esito.get("ruolo") == "staff":
            st.session_state.logged_in = True
            st.session_state.ruolo = "staff"
            st.session_state.staff_id = esito["staff"]["id"]
            st.session_state._next_menu = MENU_APPUNTAMENTI
            st.toast(f"Ciao {esito['staff']['nome']}")
            st.rerun()
        else:
            st.error("Utente o password non corretti.")
    with st.expander("Account demo"):
        st.caption(f"Titolare: `{DEFAULT_ADMIN_USERNAME}` / `{DEFAULT_ADMIN_PASSWORD}`")
        st.caption("Operatori: `giulia` / `giulia2026` · `luca` / `luca2026` · `martina` / `martina2026`")
        st.caption("L'admin crea o cambia le credenziali da Configura → Staff.")


def pagina_home():
    render_header("Il tuo salone, oggi")
    st.markdown('<h2 class="section-title"><i class="fas fa-chart-line"></i> Panoramica</h2>', unsafe_allow_html=True)
    stat = get_statistiche()
    ricavi = float(stat["ricavi_mese"] or 0)
    ricavi_txt = f"€{ricavi:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    cards = [
        (stat["totale_prenotazioni"], "Prenotazioni attive", "fa-calendar-check"),
        (stat["prenotazioni_oggi"], "Appuntamenti oggi", "fa-circle-check"),
        (stat["prenotazioni_mese"], "Questo mese", "fa-calendar-week"),
        (ricavi_txt, "Ricavi incassati", "fa-coins"),
    ]
    cols = st.columns(4, gap="small")
    for col, (val, label, icon) in zip(cols, cards):
        with col:
            html_md(
                f'<div class="metric-card">'
                f'<div class="metric-icon"><i class="fas {icon}"></i></div>'
                f'<div class="metric-value">{esc(val)}</div>'
                f'<div class="metric-label">{esc(label)}</div>'
                f"</div>"
            )
    st.markdown("---")
    today = datetime.now().strftime("%Y-%m-%d")
    prenotazioni_oggi = [p for p in get_prenotazioni(data=today) if p["stato"] != "annullata"]
    st.markdown('<h3 class="section-title"><i class="fas fa-clock"></i> Appuntamenti di oggi</h3>', unsafe_allow_html=True)
    if not prenotazioni_oggi:
        st.markdown(
            '<div class="empty-state"><i class="fas fa-spa"></i><p>Nessun appuntamento per oggi</p></div>',
            unsafe_allow_html=True,
        )
        return
    for p in prenotazioni_oggi:
        _booking_card(p)


def _booking_card(p, truncate_note=True):
    status_label = {
        "in_attesa": "In attesa",
        "confermato": "Confermato",
        "confermata": "Confermato",
        "pagato": "Pagato",
        "annullata": "Annullata",
    }.get(p["stato"], p["stato"])
    note = (p.get("note") or "").strip()
    if truncate_note and len(note) > 80:
        note = note[:80] + "..."
    extra = []
    if p.get("telefono"):
        extra.append(f'<i class="fas fa-phone"></i> {esc(p["telefono"])}')
    if p.get("email"):
        extra.append(f'<i class="fas fa-envelope"></i> {esc(p["email"])}')
    if note:
        extra.append(f'<i class="fas fa-sticky-note"></i> {esc(note)}')
    extra_html = " · ".join(extra)
    durata = p.get("durata_minuti")
    prezzo = p.get("servizio_prezzo")
    dettaglio = esc(p.get("servizio_nome") or "Servizio")
    if p.get("staff_nome"):
        dettaglio += f" · {esc(p['staff_nome'])}"
    if durata:
        dettaglio += f" · {int(durata)} min"
    if isinstance(prezzo, (int, float)):
        dettaglio += f" · €{prezzo:.2f}"
    extra_line = f'<br><span style="color:#888;font-size:0.9rem;">{extra_html}</span>' if extra_html else ""
    html_md(
        f'<div class="booking-item {esc(p["stato"])}">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;gap:1rem;flex-wrap:wrap;">'
        f"<div><strong><i class=\"fas fa-user\"></i> {esc(p['nome_cliente'])} {esc(p['cognome_cliente'])}</strong>"
        f'<br><span style="color:#666;">{esc(p["ora_prenotazione"])} — {dettaglio}</span>{extra_line}</div>'
        f'<span class="status-badge status-{esc(p["stato"])}">{status_label}</span>'
        f"</div></div>"
    )


def _reset_prenotazione():
    st.session_state.prenotazione_ok = None
    st.session_state.servizio_selezionato = None
    st.session_state.staff_selezionato = None


def pagina_prenota():
    render_header("Scegli il servizio e l'orario")
    if st.session_state.prenotazione_ok:
        _pagina_conferma_cliente()
        return

    render_steps(_calcola_passo())
    st.markdown(
        '<h2 class="section-title"><i class="fas fa-clipboard-list"></i> Cosa vuoi prenotare</h2>',
        unsafe_allow_html=True,
    )
    st.write(
        "Scegli il servizio: vedi **cosa comprende**, **quanto dura** e **il prezzo**. "
        "Poi data e orario libero — gli slot occupati o in pausa non compaiono."
    )
    servizi = get_servizi()
    if not servizi:
        st.warning("Il negozio non ha ancora pubblicato i servizi.")
        return

    n_cols = min(2, len(servizi))
    rows = [servizi[i : i + n_cols] for i in range(0, len(servizi), n_cols)]
    selected_id = st.session_state.servizio_selezionato
    for row in rows:
        cols = st.columns(n_cols)
        for col, s in zip(cols, row):
            with col:
                selected_cls = "selected" if selected_id == s["id"] else ""
                desc = s.get("descrizione") or "Chiedi in negozio i dettagli."
                html_md(
                    f'<div class="service-pick {selected_cls}">'
                    f"<h3>{esc(s['nome'])}</h3>"
                    f"<p>{esc(desc)}</p>"
                    f"<strong>{int(s['durata_minuti'])} min</strong> · €{s['prezzo']:.2f}"
                    f"</div>"
                )
                label = "Selezionato" if selected_id == s["id"] else "Prenota questo"
                if st.button(label, key=f"pick_{s['id']}", width='stretch', type="primary" if selected_id == s["id"] else "secondary"):
                    st.session_state.servizio_selezionato = s["id"]
                    st.rerun()

    if not selected_id:
        st.info("Seleziona un servizio qui sopra per continuare.")
        return

    servizio = get_servizio(selected_id)
    if not servizio or not servizio.get("attivo"):
        st.session_state.servizio_selezionato = None
        st.warning("Questo servizio non è più disponibile. Scegline un altro.")
        return

    servizio_appena_scelto = st.session_state.servizio_selezionato != st.session_state.get("_servizio_visto")
    st.session_state._servizio_visto = st.session_state.servizio_selezionato

    html_md(
        f'<div class="recap-box" id="scelta-servizio">'
        f'<h3 style="margin-top:0;color:{primario};">Hai scelto: {esc(servizio["nome"])}</h3>'
        f"<p>{esc(servizio.get('descrizione') or 'Servizio in negozio.')}</p>"
        f"<p><strong>Durata:</strong> {int(servizio['durata_minuti'])} minuti · "
        f"<strong>Prezzo:</strong> €{servizio['prezzo']:.2f}</p>"
        f'<p style="color:#666;margin-bottom:0;">L\'orario resta bloccato per tutta la durata, per la persona che scegli.</p>'
        f"</div>"
    )
    _scrolla("scelta-servizio" if servizio_appena_scelto else None)

    if is_operatore() and st.session_state.staff_id:
        st.session_state.staff_selezionato = st.session_state.staff_id
        me = get_membro(st.session_state.staff_id)
        if me:
            st.info(f"Stai prenotando per **{me['nome']}** (il tuo calendario).")

    staff_list = get_staff()
    if staff_list and not is_operatore():
        st.markdown('<h3 class="section-title"><i class="fas fa-users"></i> Chi vuoi</h3>', unsafe_allow_html=True)
        n_staff = min(3, len(staff_list))
        srows = [staff_list[i : i + n_staff] for i in range(0, len(staff_list), n_staff)]
        selected_staff = st.session_state.staff_selezionato
        for srow in srows:
            cols = st.columns(n_staff)
            for col, membro in zip(cols, srow):
                with col:
                    selected_cls = "selected" if selected_staff == membro["id"] else ""
                    foto = logo_data_uri(membro.get("foto_path") or "")
                    img = f'<img src="{foto}" alt="{esc(membro["nome"])}" />' if foto else '<div style="font-size:3rem;margin-bottom:0.4rem;"><i class="fas fa-user-circle"></i></div>'
                    html_md(
                        f'<div class="staff-pick {selected_cls}">{img}'
                        f"<h3>{esc(membro['nome'])}</h3>"
                        f"<p>{esc(membro.get('ruolo') or 'Staff')}</p></div>"
                    )
                    label = "Selezionato" if selected_staff == membro["id"] else "Scegli"
                    if st.button(label, key=f"staff_{membro['id']}", width='stretch', type="primary" if selected_staff == membro["id"] else "secondary"):
                        st.session_state.staff_selezionato = membro["id"]
                        st.rerun()
        if not st.session_state.staff_selezionato:
            st.info("Scegli chi ti seguirà, poi vedi gli orari in cui è in salone.")
            return
    elif not staff_list:
        st.session_state.staff_selezionato = None

    staff_appena_scelto = st.session_state.staff_selezionato != st.session_state.get("_staff_visto")
    st.session_state._staff_visto = st.session_state.staff_selezionato
    html_md('<div id="scelta-data"></div>')
    _scrolla("scelta-data" if staff_appena_scelto else None)

    col_data, col_ora = st.columns(2)
    with col_data:
        data_sel = st.date_input(
            "Giorno",
            value=date.today(),
            min_value=date.today(),
            max_value=date.today() + timedelta(days=90),
        )
    data_txt = data_sel.strftime("%Y-%m-%d")
    slots = get_slot_disponibili(data_txt, servizio["id"], staff_id=st.session_state.staff_selezionato)
    with col_ora:
        if slots:
            help_orari = (
                f"Apertura {impostazioni.get('orario_apertura') or '09:00'}–{impostazioni.get('orario_chiusura') or '19:00'}"
            )
            if (impostazioni.get("pausa_inizio") or "").strip() and (impostazioni.get("pausa_fine") or "").strip():
                help_orari += f", pausa {impostazioni.get('pausa_inizio')}–{impostazioni.get('pausa_fine')}"
            ora_sel = st.selectbox("Orario disponibile", slots, help=help_orari)
        else:
            st.selectbox("Orario disponibile", ["Nessuno slot libero"], disabled=True)
            ora_sel = None
    pausa_i = (impostazioni.get("pausa_inizio") or "").strip()
    pausa_f = (impostazioni.get("pausa_fine") or "").strip()
    if pausa_i and pausa_f:
        st.caption(
            f"Aperti {impostazioni.get('orario_apertura') or '09:00'}–{impostazioni.get('orario_chiusura') or '19:00'}, "
            f"pausa {pausa_i}–{pausa_f} (non prenotabile)."
        )
    if not slots:
        if st.session_state.staff_selezionato:
            st.warning("Questa persona non ha orari liberi in quella data (turno, pausa, assenza o già occupata). Prova un altro giorno o un altro membro dello staff.")
        else:
            st.warning("In questa data non ci sono orari liberi per questo servizio. Prova un altro giorno.")
        return

    st.markdown(
        '<h3 class="section-title"><i class="fas fa-user"></i> I tuoi dati</h3>',
        unsafe_allow_html=True,
    )
    with st.form("prenotazione_form"):
        # L'ordine dentro le colonne segue quello di lettura su mobile, dove
        # Streamlit le impila: Nominome -> Cognome -> Telefono -> Email.
        # Su desktop le due colonne si leggono comunque per righe.
        c1, c2 = st.columns(2)
        with c1:
            nome = st.text_input("Nome *")
            cognome = st.text_input("Cognome")
        with c2:
            telefono = st.text_input("Telefono *", placeholder="333 123 4567")
            email = st.text_input("Email (per la conferma)", placeholder="mario@email.it")
        note = st.text_area("Note per il negozio (opzionale)", placeholder="Allergie, preferenze, richiesta particolare...")
        membro = get_membro(st.session_state.staff_selezionato) if st.session_state.staff_selezionato else None
        html_md(
            f'<div class="recap-box"><strong>Riepilogo prima di inviare</strong><br>'
            f"{esc(servizio['nome'])} — {int(servizio['durata_minuti'])} min — €{servizio['prezzo']:.2f}<br>"
            f"{data_sel.strftime('%d/%m/%Y')} alle {esc(ora_sel)}"
            f"{('<br>Con ' + esc(membro['nome'])) if membro else ''}</div>"
        )
        submitted = st.form_submit_button("Invia prenotazione", width='stretch', type="primary")

    if not submitted:
        return
    if not (nome or "").strip() or not (telefono or "").strip():
        st.error("Compila almeno nome e telefono.")
        st.toast("Mancano nome o telefono", icon="⚠️")
        return
    if slot_occupato(data_txt, ora_sel, servizio["id"], staff_id=st.session_state.staff_selezionato):
        st.error("Questo orario è appena stato occupato. Scegline un altro.")
        return

    pren_id = add_prenotazione(
        nome.strip(),
        (cognome or "").strip(),
        telefono.strip(),
        (email or "").strip(),
        servizio["id"],
        data_txt,
        ora_sel,
        (note or "").strip(),
        stato="in_attesa",
        staff_id=st.session_state.staff_selezionato,
    )
    pren = get_prenotazione(pren_id)
    mail_result = {"negozio": (False, "non inviata"), "cliente": (False, "non inviata")}
    try:
        mail_result = notifica_nuova_prenotazione(impostazioni, pren)
    except Exception as exc:
        mail_result = {"negozio": (False, str(exc)), "cliente": (False, "non inviata")}

    st.session_state.prenotazione_ok = {
        "prenotazione": pren,
        "mail": mail_result,
    }
    st.rerun()


def _pagina_conferma_cliente():
    payload = st.session_state.prenotazione_ok or {}
    p = payload.get("prenotazione") or {}
    mail = payload.get("mail") or {}
    negozio_ok = bool(mail.get("negozio", (False, ""))[0])
    cliente_ok = bool(mail.get("cliente", (False, ""))[0])
    st.balloons()
    html_md(
        f'<div class="card" style="border-left:4px solid #27ae60;">'
        f'<h2 style="color:#27ae60;margin-top:0;"><i class="fas fa-check-circle"></i> Richiesta inviata</h2>'
        f"<p>Il negozio ha ricevuto la prenotazione. Stato attuale: <strong>in attesa di conferma</strong>.</p>"
        f"<h3>Cosa hai prenotato</h3>"
        f"<p><strong>{esc(p.get('servizio_nome'))}</strong><br>{esc(p.get('servizio_descrizione') or '')}</p>"
        f"<p><strong>Quando:</strong> {_fmt_data(p.get('data_prenotazione'))} alle {esc(p.get('ora_prenotazione'))}<br>"
        f"<strong>Durata:</strong> {esc(p.get('durata_minuti'))} minuti · "
        f"<strong>Prezzo:</strong> €{(p.get('servizio_prezzo') or 0):.2f}</p>"
        f"<p><strong>A nome di:</strong> {esc(p.get('nome_cliente'))} {esc(p.get('cognome_cliente'))}<br>"
        f"<strong>Telefono:</strong> {esc(p.get('telefono'))}"
        f"{('<br><strong>Ti segue:</strong> ' + esc(p.get('staff_nome'))) if p.get('staff_nome') else ''}</p></div>"
    )
    if negozio_ok:
        st.success("Abbiamo avvisato il negozio via email.")
    else:
        st.info("La prenotazione è salvata in agenda. Il negozio la vede dalla sezione Gestione.")
    if p.get("email"):
        if cliente_ok:
            st.success(f"Ti abbiamo inviato una copia a {p.get('email')}.")
        else:
            st.caption("Non è partita l'email di copia al cliente (SMTP non configurato o indirizzo non valido).")
    if st.button("Nuova prenotazione", width='stretch'):
        _reset_prenotazione()
        st.rerun()


def _fmt_data(data_iso):
    try:
        y, m, d = str(data_iso).split("-")
        return f"{d}/{m}/{y}"
    except Exception:
        return esc(data_iso)


def pagina_gestione(solo_staff_id=None):
    if solo_staff_id:
        me = get_membro(solo_staff_id)
        render_header(f"I tuoi appuntamenti{(' · ' + me['nome']) if me else ''}")
        st.markdown('<h2 class="section-title"><i class="fas fa-calendar-day"></i> La tua agenda</h2>', unsafe_allow_html=True)
        st.caption("Vedi solo gli appuntamenti assegnati a te. Puoi confermare, segnare il pagamento o annullare.")
        tab1 = st.container()
        tab2 = tab3 = None
    else:
        render_header("Gestione prenotazioni")
        st.markdown('<h2 class="section-title"><i class="fas fa-tasks"></i> Agenda</h2>', unsafe_allow_html=True)
        tab1, tab2, tab3 = st.tabs(["Agenda", "Statistiche", "Elimina"])
    with tab1:
        data_selezionata = st.date_input("Seleziona data", value=datetime.now())
        pren = get_prenotazioni(
            data=data_selezionata.strftime("%Y-%m-%d"),
            staff_id=solo_staff_id,
        )
        if not pren:
            st.markdown(
                '<div class="empty-state"><i class="fas fa-calendar-xmark"></i><p>Nessuna prenotazione per questa data</p></div>',
                unsafe_allow_html=True,
            )
        for p in pren:
            _booking_card(p, truncate_note=False)
            stato = "confermato" if p["stato"] == "confermata" else p["stato"]
            col_a, col_b, col_c, col_d = st.columns(4)
            with col_a:
                if stato == "in_attesa":
                    if st.button("Conferma", key=f"conf_{p['id']}", width='stretch'):
                        update_stato_prenotazione(p["id"], "confermato")
                        st.toast("Prenotazione confermata")
                        st.rerun()
            with col_b:
                if stato in ("in_attesa", "confermato"):
                    if st.button("Segna pagato", key=f"pay_{p['id']}", width='stretch', type="primary"):
                        update_stato_prenotazione(p["id"], "pagato")
                        st.toast("Incasso registrato")
                        st.rerun()
            with col_c:
                if stato == "pagato":
                    if st.button("Non pagato", key=f"unpay_{p['id']}", width='stretch'):
                        update_stato_prenotazione(p["id"], "confermato")
                        st.rerun()
                elif stato == "confermato":
                    if st.button("In attesa", key=f"att_{p['id']}", width='stretch'):
                        update_stato_prenotazione(p["id"], "in_attesa")
                        st.rerun()
            with col_d:
                if stato != "annullata":
                    if st.button("Annulla", key=f"ann_{p['id']}", width='stretch', type="secondary"):
                        update_stato_prenotazione(p["id"], "annullata")
                        st.rerun()
            staff_all = get_staff(includi_inattivi=True)
            if staff_all and p["stato"] != "annullata" and not solo_staff_id:
                ids = [s["id"] for s in staff_all]
                labels = {
                    s["id"]: s["nome"] + ("" if s.get("attivo") else " (non in servizio)")
                    for s in staff_all
                }
                attuale = p.get("staff_id") if p.get("staff_id") in ids else ids[0]
                nuovo = st.selectbox(
                    "Staff per questo appuntamento",
                    ids,
                    index=ids.index(attuale),
                    format_func=lambda i: labels.get(i, "—"),
                    key=f"rs_{p['id']}",
                )
                if st.button("Cambia staff", key=f"rsbtn_{p['id']}"):
                    if slot_occupato(
                        p["data_prenotazione"],
                        p["ora_prenotazione"],
                        p["servizio_id"],
                        exclude_id=p["id"],
                        staff_id=nuovo,
                    ):
                        st.error("Quella persona è occupata o non lavora in quell'orario. Scegline un'altra.")
                    else:
                        update_prenotazione_staff(p["id"], nuovo)
                        st.toast("Staff aggiornato")
                        st.rerun()
    if tab2 is None:
        return
    with tab2:
        stat = get_statistiche()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Attive", stat["totale_prenotazioni"])
        c2.metric("Oggi", stat["prenotazioni_oggi"])
        c3.metric("Mese", stat["prenotazioni_mese"])
        c4.metric("Ricavi incassati", f"€{stat['ricavi_mese']:.2f}")
        all_pre = get_prenotazioni()
        if all_pre:
            df = pd.DataFrame(all_pre)
            colonne = [
                c
                for c in [
                    "nome_cliente",
                    "cognome_cliente",
                    "data_prenotazione",
                    "ora_prenotazione",
                    "servizio_nome",
                    "staff_nome",
                    "durata_minuti",
                    "servizio_prezzo",
                    "stato",
                    "telefono",
                    "email",
                ]
                if c in df.columns
            ]
            st.dataframe(df[colonne], width='stretch', hide_index=True)
        else:
            st.info("Ancora nessuna prenotazione.")
    with tab3:
        st.write("Puoi cancellare solo le prenotazioni già annullate.")
        all_pre = get_prenotazioni(stato="annullata")
        if not all_pre:
            st.info("Nessuna prenotazione annullata da eliminare.")
        for p in all_pre:
            _booking_card(p)
            if st.button("Elimina definitivamente", key=f"elim_{p['id']}", width='stretch', type="secondary"):
                cancella_prenotazione(p["id"])
                st.toast("Prenotazione eliminata")
                st.rerun()


def _salva_logo(file, prefisso=""):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    nome, est = os.path.splitext(os.path.basename(file.name))
    est = est.lower()
    path = os.path.join(UPLOAD_DIR, f"{prefisso}{nome}{est}")
    i = 1
    # Senza questo, un file con lo stesso nome sovrascriverebbe logo o foto staff.
    while os.path.exists(path):
        path = os.path.join(UPLOAD_DIR, f"{prefisso}{nome}_{i}{est}")
        i += 1
    with open(path, "wb") as handle:
        handle.write(file.getbuffer())
    return "uploads/" + os.path.basename(path)


def pagina_configura():
    st.markdown('<h2 class="section-title"><i class="fas fa-sliders-h"></i> Configura attività</h2>', unsafe_allow_html=True)
    imp = get_impostazioni()
    tab_brand, tab_servizi, tab_staff, tab_orari, tab_email, tab_accesso = st.tabs(
        ["Branding", "Servizi", "Staff", "Orari", "Email", "Accesso"]
    )

    with tab_brand:
        with st.form("config_brand"):
            nome = st.text_input("Nome attività", value=imp.get("nome_attivita") or "")
            indirizzo = st.text_input("Indirizzo", value=imp.get("indirizzo") or "")
            telefono = st.text_input("Telefono", value=imp.get("telefono") or "")
            email = st.text_input(
                "Email negozio (notifiche, anche più indirizzi separati da virgola)",
                value=imp.get("email") or "",
            )
            logo = st.file_uploader("Logo", type=["png", "jpg", "jpeg", "webp"])
            sfondo = st.file_uploader(
                "Foto di sfondo del blocco in alto",
                type=["png", "jpg", "jpeg", "webp"],
                help="Viene stretchata su tutto il banner. Il nome e i contatti restano leggibili sopra una velatura semitrasparente.",
            )
            if (imp.get("sfondo_header") or "") and not sfondo:
                st.caption(f"Sfondo attuale: {imp['sfondo_header']} — carica un'altra foto per sostituirlo.")
            togli_sfondo = st.checkbox("Togli foto di sfondo", value=False)
            c1, c2 = st.columns(2)
            with c1:
                prim = st.color_picker("Colore primario", value=imp.get("colore_primario") or "#1E3A5F")
            with c2:
                sec = st.color_picker("Colore secondario", value=imp.get("colore_secondario") or "#E94560")
            if st.form_submit_button("Salva branding", type="primary", width='stretch'):
                logo_path = imp.get("logo_path") or ""
                if logo:
                    logo_path = _salva_logo(logo)
                sfondo_path = imp.get("sfondo_header") or ""
                if sfondo:
                    sfondo_path = _salva_logo(sfondo, "sfondo_")
                elif togli_sfondo:
                    sfondo_path = ""
                update_impostazioni(
                    nome_attivita=nome,
                    indirizzo=indirizzo,
                    telefono=telefono,
                    email=email,
                    logo_path=logo_path,
                    sfondo_header=sfondo_path,
                    colore_primario=prim,
                    colore_secondario=sec,
                )
                st.toast("Branding salvato")
                st.rerun()

    with tab_servizi:
        servizi = get_servizi(includi_disattivi=True)
        with st.form("config_servizi"):
            st.write("Modifica i servizi visibili ai clienti. La descrizione compare nella prenotazione.")
            for s in servizi:
                st.markdown(f"**{esc(s['nome'])}**")
                c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                c1.text_input("Nome", value=s["nome"], key=f"sn_{s['id']}")
                c2.number_input("Prezzo €", value=float(s["prezzo"]), step=0.5, min_value=0.0, key=f"sp_{s['id']}")
                c3.number_input("Durata min", value=int(s["durata_minuti"]), step=5, min_value=5, key=f"sd_{s['id']}")
                c4.checkbox("Attivo", value=bool(s["attivo"]), key=f"sa_{s['id']}")
                st.text_input("Descrizione", value=s.get("descrizione") or "", key=f"sdesc_{s['id']}")
                st.markdown("---")
            st.subheader("Nuovo servizio")
            n1, n2, n3 = st.columns(3)
            nuovo_nome = n1.text_input("Nome nuovo servizio")
            nuovo_prezzo = n2.number_input("Prezzo nuovo €", value=0.0, step=0.5, min_value=0.0)
            nuova_dur = n3.number_input("Durata nuova min", value=60, step=5, min_value=5)
            nuova_desc = st.text_input("Descrizione nuovo servizio")
            if st.form_submit_button("Salva servizi", type="primary", width='stretch'):
                for s in servizi:
                    update_servizio(
                        s["id"],
                        st.session_state.get(f"sn_{s['id']}", s["nome"]),
                        st.session_state.get(f"sdesc_{s['id']}", s.get("descrizione") or ""),
                        int(st.session_state.get(f"sd_{s['id']}", s["durata_minuti"])),
                        float(st.session_state.get(f"sp_{s['id']}", s["prezzo"])),
                        st.session_state.get(f"sa_{s['id']}", True),
                    )
                if (nuovo_nome or "").strip():
                    add_servizio(nuovo_nome.strip(), nuova_desc, int(nuova_dur), float(nuovo_prezzo))
                st.toast("Servizi salvati")
                st.rerun()

    with tab_staff:
        st.write(
            "Ogni persona ha **foto**, **orari della settimana** e può essere tolta **momentaneamente** "
            "(malattia, ferie): sparisce dalla prenotazione online. "
            "Da Agenda puoi spostare un appuntamento su un collega."
        )
        for membro in get_staff(includi_inattivi=True):
            titolo = membro["nome"] + ("" if membro.get("attivo") else " · non in servizio")
            with st.expander(titolo, expanded=False):
                foto = logo_data_uri(membro.get("foto_path") or "")
                if foto:
                    html_md(f'<img src="{foto}" alt="" style="width:72px;height:72px;border-radius:50%;object-fit:cover;" />')
                c1, c2 = st.columns(2)
                nome_s = c1.text_input("Nome", value=membro["nome"], key=f"stn_{membro['id']}")
                ruolo_s = c2.text_input("Ruolo", value=membro.get("ruolo") or "", key=f"str_{membro['id']}")
                in_servizio = st.checkbox(
                    "In servizio (se lo togli, i clienti non lo vedono)",
                    value=bool(membro.get("attivo")),
                    key=f"sta_{membro['id']}",
                )
                nuova_foto = st.file_uploader(
                    "Foto",
                    type=["png", "jpg", "jpeg", "webp"],
                    key=f"stf_{membro['id']}",
                )
                if st.button("Salva profilo", key=f"stsave_{membro['id']}"):
                    foto_path = membro.get("foto_path") or ""
                    if nuova_foto:
                        foto_path = _salva_logo(nuova_foto)
                    update_staff(membro["id"], nome_s, ruolo_s, foto_path, in_servizio)
                    st.toast("Profilo staff salvato")
                    st.rerun()
                st.markdown("**Accesso operatore**")
                st.caption("L'operatore entra da Area riservata e vede solo i suoi appuntamenti.")
                u1, u2 = st.columns(2)
                user_s = u1.text_input(
                    "Utente",
                    value=membro.get("username") or "",
                    key=f"stu_{membro['id']}",
                    placeholder="es. giulia",
                )
                pwd_s = u2.text_input(
                    "Nuova password",
                    type="password",
                    key=f"stp_{membro['id']}",
                    placeholder="Lascia vuoto per non cambiare",
                )
                if membro.get("username"):
                    st.caption(f"Login attuale: `{membro.get('username')}`")
                else:
                    st.caption("Nessun accesso: imposta utente e password.")
                if st.button("Salva credenziali", key=f"stcred_{membro['id']}"):
                    ok, err = set_staff_credenziali(membro["id"], user_s, pwd_s)
                    if ok:
                        st.toast("Credenziali aggiornate")
                        st.rerun()
                    else:
                        st.error(err)
                st.markdown("**Orari della settimana**")
                orari = get_staff_orari(membro["id"])
                nuovi = []
                for r in orari:
                    d = int(r["weekday"])
                    cols = st.columns([2, 1, 1, 1])
                    lavora = cols[0].checkbox(GIORNI[d], value=bool(r.get("lavora")), key=f"stl_{membro['id']}_{d}")
                    inizio = cols[1].text_input("Dalle", value=r.get("ora_inizio") or "09:00", key=f"sti_{membro['id']}_{d}")
                    fine = cols[2].text_input("Alle", value=r.get("ora_fine") or "19:00", key=f"ste_{membro['id']}_{d}")
                    nuovi.append({"weekday": d, "lavora": lavora, "ora_inizio": inizio, "ora_fine": fine})
                if st.button("Salva orari", key=f"stor_{membro['id']}"):
                    set_staff_orari(membro["id"], nuovi)
                    st.toast("Orari aggiornati")
                    st.rerun()
                st.markdown("**Assenze (malattia / giorno via)**")
                oggi = date.today().strftime("%Y-%m-%d")
                assenze = get_assenze(membro["id"], da_data=oggi)
                if assenze:
                    for a in assenze:
                        ac1, ac2 = st.columns([3, 1])
                        ac1.write(_fmt_data(a["data"]))
                        if ac2.button("Togli", key=f"astdel_{a['id']}"):
                            remove_assenza(a["id"])
                            st.rerun()
                else:
                    st.caption("Nessuna assenza futura.")
                giorno_ass = st.date_input("Aggiungi assenza", value=date.today(), key=f"astd_{membro['id']}")
                if st.button("Segna assente", key=f"astadd_{membro['id']}"):
                    add_assenza(membro["id"], giorno_ass.strftime("%Y-%m-%d"))
                    st.toast("Assenza registrata: quel giorno non è prenotabile")
                    st.rerun()
        st.markdown("---")
        st.subheader("Nuovo membro")
        with st.form("nuovo_staff"):
            nn, nr = st.columns(2)
            nuovo_nome_s = nn.text_input("Nome")
            nuovo_ruolo_s = nr.text_input("Ruolo", placeholder="Colorista, stylist…")
            nu, np = st.columns(2)
            nuovo_user_s = nu.text_input("Utente accesso", placeholder="es. anna")
            nuovo_pwd_s = np.text_input("Password accesso", type="password")
            nuova_foto_s = st.file_uploader("Foto", type=["png", "jpg", "jpeg", "webp"])
            if st.form_submit_button("Aggiungi staff", type="primary"):
                if not (nuovo_nome_s or "").strip():
                    st.error("Serve almeno il nome.")
                else:
                    foto_path = _salva_logo(nuova_foto_s) if nuova_foto_s else ""
                    sid = add_staff(nuovo_nome_s.strip(), nuovo_ruolo_s.strip(), foto_path)
                    if (nuovo_user_s or "").strip() or (nuovo_pwd_s or "").strip():
                        ok, err = set_staff_credenziali(sid, nuovo_user_s, nuovo_pwd_s)
                        if not ok:
                            st.warning(f"Membro creato, ma accesso non salvato: {err}")
                            st.stop()
                    st.toast("Membro aggiunto")
                    st.rerun()

    with tab_orari:
        st.write(
            "Il cliente vede solo gli orari in cui il servizio **inizia e finisce** dentro l'apertura, "
            "senza entrare nella pausa. Esempio: aperti 09:00–19:00, pausa 13:00–14:00 → "
            "un taglio da 45 minuti non può partire alle 12:30."
        )
        with st.form("config_orari"):
            c1, c2, c3 = st.columns(3)
            apertura = c1.text_input("Apertura (HH:MM)", value=imp.get("orario_apertura") or "09:00")
            chiusura = c2.text_input("Chiusura (HH:MM)", value=imp.get("orario_chiusura") or "19:00")
            slot = c3.number_input("Intervallo slot (minuti)", value=int(imp.get("slot_minuti") or 15), min_value=5, step=5)
            st.markdown("**Pausa (opzionale)** — lascia vuoto se non chiudi a metà giornata.")
            p1, p2 = st.columns(2)
            pausa_inizio = p1.text_input(
                "Pausa dalle",
                value=imp.get("pausa_inizio") or "",
                placeholder="13:00",
            )
            pausa_fine = p2.text_input(
                "Pausa alle",
                value=imp.get("pausa_fine") or "",
                placeholder="14:00",
            )
            if st.form_submit_button("Salva orari", type="primary", width='stretch'):
                inizio = (pausa_inizio or "").strip()
                fine = (pausa_fine or "").strip()
                if (inizio and not fine) or (fine and not inizio):
                    st.error("Inserisci sia inizio sia fine della pausa, oppure lascia entrambi vuoti.")
                elif inizio and fine and fine <= inizio:
                    st.error("L'orario di fine pausa deve essere dopo l'inizio.")
                else:
                    update_impostazioni(
                        orario_apertura=apertura,
                        orario_chiusura=chiusura,
                        pausa_inizio=inizio,
                        pausa_fine=fine,
                        slot_minuti=int(slot),
                    )
                    st.toast("Orari salvati")
                    st.rerun()

    with tab_email:
        st.write(
            "Quando un cliente prenota, parte una email al **negozio** e, se ha lasciato l'indirizzo, una copia al cliente. "
            "Per Gmail: attiva la verifica in 2 passaggi e usa una **password per le app**, non la password normale."
        )
        with st.form("config_email"):
            smtp_host = st.text_input("SMTP host", value=imp.get("smtp_host") or "smtp.gmail.com")
            smtp_port = st.number_input("SMTP porta", value=int(imp.get("smtp_port") or 587), min_value=1, step=1)
            smtp_user = st.text_input("SMTP utente (la tua Gmail)", value=imp.get("smtp_user") or "")
            smtp_password = st.text_input(
                "SMTP password / password per le app",
                type="password",
                help="Lascia vuoto per non cambiare la password già salvata.",
            )
            invia_cliente = st.checkbox(
                "Invia anche una copia al cliente",
                value=bool(int(imp.get("invia_email_cliente") or 0)),
            )
            if st.form_submit_button("Salva email", type="primary", width='stretch'):
                payload = {
                    "smtp_host": smtp_host,
                    "smtp_port": int(smtp_port),
                    "smtp_user": smtp_user,
                    "invia_email_cliente": 1 if invia_cliente else 0,
                }
                if smtp_password.strip():
                    payload["smtp_password"] = smtp_password.strip()
                update_impostazioni(**payload)
                st.toast("Impostazioni email salvate")
                st.rerun()
        if st.button("Invia email di prova al negozio"):
            runtime = load_impostazioni()
            dest = (runtime.get("email") or runtime.get("smtp_user") or "").strip()
            ok, err = invia_email(
                runtime,
                dest,
                "Test prenotazioni",
                "Se leggi questa email, l'invio SMTP funziona.",
            )
            if ok:
                st.success(f"Email di prova inviata a {dest}")
            else:
                st.error(f"Invio non riuscito: {err}")

    with tab_accesso:
        with st.form("config_accesso"):
            admin_user = st.text_input("Utente admin", value=imp.get("admin_username") or DEFAULT_ADMIN_USERNAME)
            nuova_pwd = st.text_input("Nuova password", type="password")
            conferma_pwd = st.text_input("Conferma password", type="password")
            if st.form_submit_button("Salva accesso", type="primary", width='stretch'):
                fields = {"admin_username": admin_user.strip() or DEFAULT_ADMIN_USERNAME}
                if nuova_pwd or conferma_pwd:
                    if nuova_pwd != conferma_pwd:
                        st.error("Le password non coincidono.")
                        return
                    if len(nuova_pwd) < 6:
                        st.error("Usa almeno 6 caratteri.")
                        return
                    fields["admin_password_hash"] = hash_password(nuova_pwd)
                update_impostazioni(**fields)
                st.toast("Accesso aggiornato")
                st.rerun()


def main():
    global impostazioni, primario, secondario
    impostazioni = load_impostazioni()
    primario = impostazioni.get("colore_primario") or "#1E3A5F"
    secondario = impostazioni.get("colore_secondario") or "#E94560"
    _sync_auth_cookie()

    opzioni = _prepara_menu()
    pagina = st.session_state.menu
    # Vero solo cambiando sezione: i rerun interni della stessa pagina
    # (scegliere un servizio, cambiare un filtro) non devono animare nulla.
    cambio_sezione = st.session_state.get("_sezione") != pagina
    st.session_state._sezione = pagina

    inject_css(cambio_sezione)
    if cambio_sezione:
        _scrolla_in_cima()
    topnav_setup(opzioni)
    if pagina == MENU_ESCI:
        st.session_state._pending_logout = True
        st.rerun()
    if pagina == MENU_AREA:
        pagina_login()
        return
    if pagina in (MENU_HOME, MENU_GESTIONE, MENU_CONFIGURA) and not is_admin():
        if is_operatore():
            pagina_gestione(solo_staff_id=st.session_state.staff_id)
            html_md(
                f'<p class="product-foot">© {datetime.now().year} {esc(impostazioni.get("nome_attivita") or "")}'
                f" · prenotazione diretta, senza commissioni</p>"
            )
            return
        pagina_login()
        return
    if pagina == MENU_HOME:
        pagina_home()
    elif pagina == MENU_APPUNTAMENTI:
        if not is_operatore():
            pagina_login()
            return
        pagina_gestione(solo_staff_id=st.session_state.staff_id)
    elif pagina == MENU_PRENOTA:
        pagina_prenota()
    elif pagina == MENU_GESTIONE:
        pagina_gestione()
    elif pagina == MENU_CONFIGURA:
        pagina_configura()
    else:
        st.error(f"Rotta di menu sconosciuta: {pagina!r}")
        st.stop()
    html_md(
        f'<p class="product-foot">© {datetime.now().year} {esc(impostazioni.get("nome_attivita") or "")}'
        f" · prenotazione diretta, senza commissioni</p>"
    )


if __name__ == "__main__":
    main()
