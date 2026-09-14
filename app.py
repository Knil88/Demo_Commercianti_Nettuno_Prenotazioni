import base64
import html
import os
import textwrap
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

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
    set_staff_orari,
    slot_occupato,
    update_impostazioni,
    update_prenotazione_staff,
    update_servizio,
    update_staff,
    update_stato_prenotazione,
    verify_admin,
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


_boot = get_impostazioni()
st.set_page_config(
    page_title=f"{_boot.get('nome_attivita') or 'Prenota'} · Prenota online",
    page_icon=_page_icon(),
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"Get help": None, "Report a bug": None, "About": None},
)

impostazioni = load_impostazioni()
primario = impostazioni.get("colore_primario") or "#1E3A5F"
secondario = impostazioni.get("colore_secondario") or "#E94560"

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "servizio_selezionato" not in st.session_state:
    st.session_state.servizio_selezionato = None
if "prenotazione_ok" not in st.session_state:
    st.session_state.prenotazione_ok = None
if "staff_selezionato" not in st.session_state:
    st.session_state.staff_selezionato = None


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


def inject_css():
    html_md(
        f"""
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
* {{ box-sizing: border-box; }}
.stApp {{ background-color: #F4F1EC; font-family: 'Inter', sans-serif; }}
.block-container {{ padding-top: 2.2rem; max-width: 1100px; }}
section[data-testid="stSidebar"] {{ background: #fff; }}
section[data-testid="stSidebar"] .stRadio > label {{ display: none; }}
@keyframes fadeInUp {{ from {{ opacity: 0; transform: translateY(20px); }} to {{ opacity: 1; transform: translateY(0); }} }}
@keyframes fadeInDown {{ from {{ opacity: 0; transform: translateY(-20px); }} to {{ opacity: 1; transform: translateY(0); }} }}
@keyframes slideInLeft {{ from {{ opacity: 0; transform: translateX(-16px); }} to {{ opacity: 1; transform: translateX(0); }} }}
@keyframes expandLine {{ to {{ width: 100%; }} }}
.header {{
    background: linear-gradient(135deg, {primario}, {secondario});
    padding: 1.8rem 1.5rem; border-radius: 16px; color: #fff; text-align: center;
    margin-bottom: 1.5rem; box-shadow: 0 8px 32px rgba(0,0,0,0.2);
    animation: fadeInDown 0.6s ease-out;
}}
.header img {{ width: 90px; height: 90px; object-fit: cover; border-radius: 12px; margin-bottom: 0.6rem; }}
.header h1 {{ font-size: 2rem; margin: 0; color: #fff; }}
.header p {{ margin: 0.4rem 0 0; opacity: 0.95; font-size: 1rem; color: #fff; }}
.metric-card {{
    background: white; padding: 1.15rem 0.7rem 1.05rem;
    border-radius: 16px; box-shadow: 0 4px 16px rgba(0,0,0,0.08);
    text-align: center; border-top: 4px solid {primario};
    animation: fadeInUp 0.5s ease-out both;
    min-height: 148px; height: 100%;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
}}
.metric-icon {{ font-size: 1.35rem; color: {primario}; margin-bottom: 0.4rem; line-height: 1; }}
.metric-value {{
    font-size: 1.7rem; font-weight: 700; color: {primario};
    line-height: 1.15; white-space: nowrap; letter-spacing: -0.02em;
}}
.metric-label {{ color: #888; font-size: 0.78rem; margin-top: 0.35rem; line-height: 1.25; }}
[data-testid="stHeaderActionElements"] {{ display: none !important; }}
.card, .booking-item, .service-pick, .recap-box {{
    background: white; border-radius: 12px; padding: 1.2rem 1.4rem;
    margin-bottom: 0.6rem; box-shadow: 0 4px 16px rgba(0,0,0,0.08);
}}
.booking-item {{ border-left: 4px solid {secondario}; animation: slideInLeft 0.35s ease-out both; }}
.booking-item.confermato, .booking-item.confermata {{ border-left-color: #27ae60; }}
.booking-item.pagato {{ border-left-color: #1a7f9e; }}
.booking-item.in_attesa {{ border-left-color: #f39c12; }}
.booking-item.annullata {{ border-left-color: #95a5a6; opacity: 0.7; }}
.status-badge {{ display: inline-block; padding: 0.25rem 0.75rem; border-radius: 20px; font-size: 0.8rem; font-weight: 600; }}
.status-confermato, .status-confermata {{ background: #d4edda; color: #155724; }}
.status-pagato {{ background: #d6eef6; color: #0c5460; }}
.status-in_attesa {{ background: #fff3cd; color: #856404; }}
.status-annullata {{ background: #e2e3e5; color: #383d41; }}
.section-title {{
    font-size: 1.4rem; font-weight: 600; color: {primario};
    border-bottom: 3px solid {primario}; padding-bottom: 0.5rem; margin-bottom: 1.2rem;
    position: relative; display: inline-block;
}}
.section-title::after {{
    content: ''; position: absolute; bottom: -3px; left: 0; width: 0; height: 3px;
    background: {secondario}; animation: expandLine 0.8s ease-out 0.2s forwards;
}}
.empty-state {{ text-align: center; padding: 3rem; color: #888; }}
.empty-state i {{ font-size: 3rem; margin-bottom: 1rem; display: block; color: {primario}; }}
.service-pick {{
    border-left: 4px solid {primario};
    min-height: 170px;
    height: 100%;
}}
.service-pick.selected {{ border-left-color: {secondario}; box-shadow: 0 8px 24px rgba(0,0,0,0.12); }}
.service-pick h3 {{
    margin: 0 0 0.45rem; color: {primario}; font-size: 1.35rem; line-height: 1.25;
    word-break: normal; overflow-wrap: break-word; hyphens: none;
}}
.service-pick p {{ color: #555; font-size: 0.95rem; margin: 0 0 0.8rem; min-height: 2.6em; }}
.recap-box {{ border-left: 4px solid {primario}; }}
.staff-pick {{
    border-left: 4px solid {primario};
    text-align: center;
    min-height: 210px;
}}
.staff-pick.selected {{ border-left-color: {secondario}; box-shadow: 0 8px 24px rgba(0,0,0,0.12); }}
.staff-pick.offline {{ opacity: 0.5; }}
.staff-pick img {{
    width: 88px; height: 88px; border-radius: 50%; object-fit: cover;
    margin: 0 auto 0.6rem; display: block; background: #eee;
}}
.staff-pick h3 {{ margin: 0.2rem 0 0.15rem; color: {primario}; font-size: 1.05rem; }}
.staff-pick p {{ color: #666; font-size: 0.85rem; margin: 0; }}
.stButton > button {{ border-radius: 10px; }}
.product-foot {{ text-align: center; color: #8a8a8a; font-size: 0.8rem; margin-top: 2.5rem; padding-bottom: 1rem; }}
</style>
"""
    )


def render_header(subtitle=None):
    nome = esc(impostazioni.get("nome_attivita") or "La Mia Attività")
    indirizzo = esc(impostazioni.get("indirizzo") or "")
    telefono = esc(impostazioni.get("telefono") or "")
    email = esc(impostazioni.get("email") or "")
    uri = logo_data_uri(impostazioni.get("logo_path") or "")
    logo_html = (
        f'<img src="{uri}" alt="Logo" />'
        if uri
        else '<div style="font-size:3rem;margin-bottom:0.4rem;"><i class="fas fa-calendar-check"></i></div>'
    )
    parts = [f'<div class="header">{logo_html}<h1>{nome}</h1>']
    if indirizzo:
        parts.append(f'<p><i class="fas fa-map-marker-alt"></i> {indirizzo}</p>')
    if telefono:
        parts.append(f'<p><i class="fas fa-phone"></i> {telefono}</p>')
    if email:
        parts.append(f'<p><i class="fas fa-envelope"></i> {email}</p>')
    if subtitle:
        parts.append(f"<p>{esc(subtitle)}</p>")
    parts.append("</div>")
    html_md("".join(parts))


def sidebar_setup():
    if st.session_state.logged_in:
        options = ["🏠 Home", "📅 Prenota", "📋 Gestione", "⚙️ Configura", "🚪 Esci"]
    else:
        options = ["📅 Prenota", "🔐 Area riservata"]
    # Cambia pagina solo prima di st.radio(key="menu"), mai dopo.
    next_menu = st.session_state.pop("_next_menu", None)
    if next_menu in options:
        st.session_state.menu = next_menu
    elif st.session_state.get("menu") not in options:
        st.session_state.menu = options[0]
    with st.sidebar:
        uri = logo_data_uri(impostazioni.get("logo_path") or "")
        logo_bit = f'<img src="{uri}" alt="logo" style="width:64px;height:64px;object-fit:cover;border-radius:12px;margin-bottom:0.6rem;" />' if uri else '<i class="fas fa-scissors" style="font-size:1.6rem;"></i>'
        html_md(
            f'<div style="background:linear-gradient(135deg,{primario},{secondario});padding:1.4rem 1.2rem;border-radius:16px;color:white;text-align:center;margin-bottom:1rem;">'
            f"{logo_bit}"
            f'<p style="margin:0.35rem 0 0;font-weight:700;font-size:1.05rem;">{esc(impostazioni.get("nome_attivita") or "Prenota")}</p>'
            f'<p style="margin:0.25rem 0 0;opacity:0.9;font-size:0.8rem;">Prenotazione online</p>'
            f"</div>"
        )
        pagina = st.radio("Menu", options, key="menu", label_visibility="collapsed")
        if st.session_state.logged_in:
            st.caption("Sei nell'area staff")
        else:
            st.caption("Prenota come cliente · lo staff conferma l'appuntamento")
        if st.session_state.logged_in and not smtp_configurato(impostazioni):
            st.warning("Email non configurata: le nuove prenotazioni non avvisano il negozio.")
        html_md(
            f'<p class="product-foot" style="margin-top:1.5rem;">'
            f'{esc(impostazioni.get("orario_apertura") or "09:00")}–{esc(impostazioni.get("orario_chiusura") or "19:00")}'
            f'{(" · pausa " + esc(impostazioni.get("pausa_inizio")) + "–" + esc(impostazioni.get("pausa_fine"))) if (impostazioni.get("pausa_inizio") or "").strip() else ""}'
            f"</p>"
        )
    return pagina


def _login_ok(username, password):
    try:
        admin = dict(_secrets().get("admin", {}) or {})
        su, sp = admin.get("username"), admin.get("password")
        if su and sp and username.strip() == str(su).strip() and password == str(sp):
            return True
    except Exception:
        pass
    return verify_admin(username, password)


def pagina_login():
    render_header("Area staff")
    st.markdown('<h2 class="section-title"><i class="fas fa-lock"></i> Accedi</h2>', unsafe_allow_html=True)
    st.write("Solo il titolare e lo staff gestiscono agenda e impostazioni.")
    with st.form("login_form"):
        username = st.text_input("Utente")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Entra", use_container_width=True, type="primary")
    if submitted:
        if _login_ok(username, password):
            st.session_state.logged_in = True
            st.session_state._next_menu = "🏠 Home"
            st.toast("Accesso effettuato")
            st.rerun()
        else:
            st.error("Utente o password non corretti.")
    with st.expander("Account demo"):
        st.caption(f"Utente `{DEFAULT_ADMIN_USERNAME}` · password `{DEFAULT_ADMIN_PASSWORD}`")
        st.caption("In produzione cambiala da Impostazioni → Accesso, oppure usa i Secrets del deploy.")


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
                if st.button(label, key=f"pick_{s['id']}", use_container_width=True, type="primary" if selected_id == s["id"] else "secondary"):
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

    html_md(
        f'<div class="recap-box">'
        f'<h3 style="margin-top:0;color:{primario};">Hai scelto: {esc(servizio["nome"])}</h3>'
        f"<p>{esc(servizio.get('descrizione') or 'Servizio in negozio.')}</p>"
        f"<p><strong>Durata:</strong> {int(servizio['durata_minuti'])} minuti · "
        f"<strong>Prezzo:</strong> €{servizio['prezzo']:.2f}</p>"
        f'<p style="color:#666;margin-bottom:0;">L\'orario resta bloccato per tutta la durata, per la persona che scegli.</p>'
        f"</div>"
    )

    staff_list = get_staff()
    if staff_list:
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
                    if st.button(label, key=f"staff_{membro['id']}", use_container_width=True, type="primary" if selected_staff == membro["id"] else "secondary"):
                        st.session_state.staff_selezionato = membro["id"]
                        st.rerun()
        if not st.session_state.staff_selezionato:
            st.info("Scegli chi ti seguirà, poi vedi gli orari in cui è in salone.")
            return
    else:
        st.session_state.staff_selezionato = None

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

    st.markdown('<h3 class="section-title"><i class="fas fa-user"></i> I tuoi dati</h3>', unsafe_allow_html=True)
    with st.form("prenotazione_form"):
        c1, c2 = st.columns(2)
        with c1:
            nome = st.text_input("Nome *")
            telefono = st.text_input("Telefono *", placeholder="333 123 4567")
        with c2:
            cognome = st.text_input("Cognome")
            email = st.text_input("Email (per la conferma)", placeholder="mario@email.it")
        note = st.text_area("Note per il negozio (opzionale)", placeholder="Allergie, preferenze, richiesta particolare...")
        membro = get_membro(st.session_state.staff_selezionato) if st.session_state.staff_selezionato else None
        html_md(
            f'<div class="recap-box"><strong>Riepilogo prima di inviare</strong><br>'
            f"{esc(servizio['nome'])} — {int(servizio['durata_minuti'])} min — €{servizio['prezzo']:.2f}<br>"
            f"{data_sel.strftime('%d/%m/%Y')} alle {esc(ora_sel)}"
            f"{('<br>Con ' + esc(membro['nome'])) if membro else ''}</div>"
        )
        submitted = st.form_submit_button("Invia prenotazione", use_container_width=True, type="primary")

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
    if st.button("Nuova prenotazione", use_container_width=True):
        _reset_prenotazione()
        st.rerun()


def _fmt_data(data_iso):
    try:
        y, m, d = str(data_iso).split("-")
        return f"{d}/{m}/{y}"
    except Exception:
        return esc(data_iso)


def pagina_gestione():
    render_header("Gestione prenotazioni")
    st.markdown('<h2 class="section-title"><i class="fas fa-tasks"></i> Agenda</h2>', unsafe_allow_html=True)
    tab1, tab2, tab3 = st.tabs(["Agenda", "Statistiche", "Elimina"])
    with tab1:
        data_selezionata = st.date_input("Seleziona data", value=datetime.now())
        pren = get_prenotazioni(data=data_selezionata.strftime("%Y-%m-%d"))
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
                    if st.button("Conferma", key=f"conf_{p['id']}", use_container_width=True):
                        update_stato_prenotazione(p["id"], "confermato")
                        st.toast("Prenotazione confermata")
                        st.rerun()
            with col_b:
                if stato in ("in_attesa", "confermato"):
                    if st.button("Segna pagato", key=f"pay_{p['id']}", use_container_width=True, type="primary"):
                        update_stato_prenotazione(p["id"], "pagato")
                        st.toast("Incasso registrato")
                        st.rerun()
            with col_c:
                if stato == "pagato":
                    if st.button("Non pagato", key=f"unpay_{p['id']}", use_container_width=True):
                        update_stato_prenotazione(p["id"], "confermato")
                        st.rerun()
                elif stato == "confermato":
                    if st.button("In attesa", key=f"att_{p['id']}", use_container_width=True):
                        update_stato_prenotazione(p["id"], "in_attesa")
                        st.rerun()
            with col_d:
                if stato != "annullata":
                    if st.button("Annulla", key=f"ann_{p['id']}", use_container_width=True, type="secondary"):
                        update_stato_prenotazione(p["id"], "annullata")
                        st.rerun()
            staff_all = get_staff(includi_inattivi=True)
            if staff_all and p["stato"] != "annullata":
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
            st.dataframe(df[colonne], use_container_width=True, hide_index=True)
        else:
            st.info("Ancora nessuna prenotazione.")
    with tab3:
        st.write("Puoi cancellare solo le prenotazioni già annullate.")
        all_pre = get_prenotazioni(stato="annullata")
        if not all_pre:
            st.info("Nessuna prenotazione annullata da eliminare.")
        for p in all_pre:
            _booking_card(p)
            if st.button("Elimina definitivamente", key=f"elim_{p['id']}", use_container_width=True, type="secondary"):
                cancella_prenotazione(p["id"])
                st.toast("Prenotazione eliminata")
                st.rerun()


def _salva_logo(file):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filename = os.path.basename(file.name)
    path = os.path.join(UPLOAD_DIR, filename)
    with open(path, "wb") as handle:
        handle.write(file.getbuffer())
    return "uploads/" + filename


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
            c1, c2 = st.columns(2)
            with c1:
                prim = st.color_picker("Colore primario", value=imp.get("colore_primario") or "#1E3A5F")
            with c2:
                sec = st.color_picker("Colore secondario", value=imp.get("colore_secondario") or "#E94560")
            if st.form_submit_button("Salva branding", type="primary", use_container_width=True):
                logo_path = imp.get("logo_path") or ""
                if logo:
                    logo_path = _salva_logo(logo)
                update_impostazioni(
                    nome_attivita=nome,
                    indirizzo=indirizzo,
                    telefono=telefono,
                    email=email,
                    logo_path=logo_path,
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
            if st.form_submit_button("Salva servizi", type="primary", use_container_width=True):
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
            nuova_foto_s = st.file_uploader("Foto", type=["png", "jpg", "jpeg", "webp"])
            if st.form_submit_button("Aggiungi staff", type="primary"):
                if not (nuovo_nome_s or "").strip():
                    st.error("Serve almeno il nome.")
                else:
                    foto_path = _salva_logo(nuova_foto_s) if nuova_foto_s else ""
                    add_staff(nuovo_nome_s.strip(), nuovo_ruolo_s.strip(), foto_path)
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
            if st.form_submit_button("Salva orari", type="primary", use_container_width=True):
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
            if st.form_submit_button("Salva email", type="primary", use_container_width=True):
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
            if st.form_submit_button("Salva accesso", type="primary", use_container_width=True):
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
    inject_css()
    pagina = sidebar_setup()
    if pagina == "🚪 Esci":
        st.session_state.logged_in = False
        st.session_state._next_menu = "📅 Prenota"
        st.rerun()
    if pagina == "🔐 Area riservata":
        pagina_login()
        return
    if pagina in ("🏠 Home", "📋 Gestione", "⚙️ Configura") and not st.session_state.logged_in:
        pagina_login()
        return
    if pagina == "🏠 Home":
        pagina_home()
    elif pagina == "📅 Prenota":
        pagina_prenota()
    elif pagina == "📋 Gestione":
        pagina_gestione()
    elif pagina == "⚙️ Configura":
        pagina_configura()
    html_md(
        f'<p class="product-foot">© {datetime.now().year} {esc(impostazioni.get("nome_attivita") or "")}'
        f" · prenotazione diretta, senza commissioni</p>"
    )


if __name__ == "__main__":
    main()
