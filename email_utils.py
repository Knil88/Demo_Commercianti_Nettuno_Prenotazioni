import html
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, parseaddr


def smtp_configurato(impostazioni):
    return bool(
        (impostazioni.get("smtp_host") or "").strip()
        and impostazioni.get("smtp_port")
        and (impostazioni.get("smtp_user") or "").strip()
        and (impostazioni.get("smtp_password") or "").strip()
    )


def _destinatari(valore):
    if not valore:
        return []
    if isinstance(valore, (list, tuple)):
        raw = ",".join(valore)
    else:
        raw = str(valore)
    out = []
    for pezzo in raw.replace(";", ",").split(","):
        email = parseaddr(pezzo.strip())[1]
        if email and "@" in email:
            out.append(email)
    return out


def invia_email(impostazioni, destinatario, oggetto, corpo_text, corpo_html=None):
    if not smtp_configurato(impostazioni):
        return False, "SMTP non configurato. Vai su Configura e inserisci host, utente e password."

    to_list = _destinatari(destinatario)
    if not to_list:
        return False, "Nessun destinatario email valido."

    host = (impostazioni.get("smtp_host") or "smtp.gmail.com").strip()
    try:
        port = int(impostazioni.get("smtp_port") or 587)
    except (TypeError, ValueError):
        port = 587
    user = (impostazioni.get("smtp_user") or "").strip()
    password = impostazioni.get("smtp_password") or ""
    nome = impostazioni.get("nome_attivita") or "Prenotazioni"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = oggetto
    msg["From"] = formataddr((nome, user))
    msg["To"] = ", ".join(to_list)
    msg.attach(MIMEText(corpo_text, "plain", "utf-8"))
    if corpo_html:
        msg.attach(MIMEText(corpo_html, "html", "utf-8"))

    context = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=20, context=context) as server:
                server.login(user, password)
                server.sendmail(user, to_list, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=20) as server:
                server.starttls(context=context)
                server.login(user, password)
                server.sendmail(user, to_list, msg.as_string())
        return True, None
    except Exception as exc:
        return False, str(exc)


def _fmt_data(data_iso):
    try:
        y, m, d = data_iso.split("-")
        return f"{d}/{m}/{y}"
    except Exception:
        return data_iso


def _h(value):
    return html.escape("" if value is None else str(value))


def notifica_nuova_prenotazione(impostazioni, prenotazione):
    nome_attivita = impostazioni.get("nome_attivita") or "l'attività"
    cliente = f"{prenotazione.get('nome_cliente', '')} {prenotazione.get('cognome_cliente', '')}".strip()
    servizio = prenotazione.get("servizio_nome") or "Servizio"
    descrizione = prenotazione.get("servizio_descrizione") or ""
    data = _fmt_data(prenotazione.get("data_prenotazione") or "")
    ora = prenotazione.get("ora_prenotazione") or ""
    durata = prenotazione.get("durata_minuti") or ""
    prezzo = prenotazione.get("servizio_prezzo")
    prezzo_txt = f"€{prezzo:.2f}" if isinstance(prezzo, (int, float)) else ""
    telefono = prenotazione.get("telefono") or ""
    email_cliente = prenotazione.get("email") or ""
    note = prenotazione.get("note") or "—"
    stato = prenotazione.get("stato") or "in_attesa"
    staff_nome = prenotazione.get("staff_nome") or ""

    risultati = {"negozio": (False, "non inviata"), "cliente": (False, "non inviata")}

    corpo_negozio = (
        f"Nuova richiesta di prenotazione per {nome_attivita}.\n\n"
        f"Cliente: {cliente}\n"
        f"Telefono: {telefono}\n"
        f"Email: {email_cliente or '—'}\n"
        f"Servizio: {servizio}"
        + (f"\nDettaglio: {descrizione}" if descrizione else "")
        + f"\nQuando: {data} alle {ora}"
        + (f"\nDurata: {durata} minuti" if durata else "")
        + (f"\nPrezzo: {prezzo_txt}" if prezzo_txt else "")
        + (f"\nCon: {staff_nome}" if staff_nome else "")
        + f"\nStato: {stato}\n"
        f"Note: {note}\n\n"
        f"Apri l'app → Gestione per confermare o annullare."
    )
    html_negozio = f"""
    <div style="font-family:Arial,sans-serif;color:#333;">
      <h2>Nuova prenotazione</h2>
      <p>È arrivata una richiesta per <strong>{_h(nome_attivita)}</strong>.</p>
      <table cellpadding="6" style="border-collapse:collapse;">
        <tr><td>Cliente</td><td><strong>{_h(cliente)}</strong></td></tr>
        <tr><td>Telefono</td><td>{_h(telefono)}</td></tr>
        <tr><td>Email</td><td>{_h(email_cliente or '—')}</td></tr>
        <tr><td>Servizio</td><td><strong>{_h(servizio)}</strong></td></tr>
        <tr><td>Dettaglio</td><td>{_h(descrizione or '—')}</td></tr>
        <tr><td>Quando</td><td><strong>{_h(data)} alle {_h(ora)}</strong></td></tr>
        <tr><td>Durata</td><td>{_h(durata)} min</td></tr>
        <tr><td>Prezzo</td><td>{_h(prezzo_txt or '—')}</td></tr>
        <tr><td>Note</td><td>{_h(note)}</td></tr>
        {f'<tr><td>Staff</td><td>{_h(staff_nome)}</td></tr>' if staff_nome else ''}
      </table>
      <p>Apri l'app, sezione Gestione, per confermare.</p>
    </div>
    """
    destinatari_negozio = impostazioni.get("email") or impostazioni.get("smtp_user")
    risultati["negozio"] = invia_email(
        impostazioni,
        destinatari_negozio,
        f"Nuova prenotazione: {servizio} il {data} alle {ora}",
        corpo_negozio,
        html_negozio,
    )

    if int(impostazioni.get("invia_email_cliente") or 0) and email_cliente:
        corpo_cliente = (
            f"Ciao {cliente},\n\n"
            f"abbiamo ricevuto la tua prenotazione presso {nome_attivita}.\n\n"
            f"Cosa hai prenotato: {servizio}\n"
            + (f"In cosa consiste: {descrizione}\n" if descrizione else "")
            + f"Quando: {data} alle {ora}\n"
            + (f"Durata: {durata} minuti\n" if durata else "")
            + (f"Prezzo: {prezzo_txt}\n" if prezzo_txt else "")
            + (f"Ti segue: {staff_nome}\n" if staff_nome else "")
            + f"\nStato: in attesa di conferma da parte del negozio.\n"
            f"Se hai bisogno di modificare, chiama {impostazioni.get('telefono') or 'il negozio'}.\n\n"
            f"A presto,\n{nome_attivita}"
        )
        html_cliente = f"""
        <div style="font-family:Arial,sans-serif;color:#333;">
          <h2>Prenotazione ricevuta</h2>
          <p>Ciao {_h(cliente)}, abbiamo ricevuto la tua richiesta presso <strong>{_h(nome_attivita)}</strong>.</p>
          <h3>Cosa hai prenotato</h3>
          <ul>
            <li><strong>{_h(servizio)}</strong></li>
            <li>{_h(descrizione or 'Servizio prenotato in negozio')}</li>
            <li><strong>{_h(data)} alle {_h(ora)}</strong></li>
            <li>Durata: {_h(durata)} minuti</li>
            <li>Prezzo: {_h(prezzo_txt or 'da confermare')}</li>
            {f'<li>Ti segue: {_h(staff_nome)}</li>' if staff_nome else ''}
          </ul>
          <p>Lo stato è <strong>in attesa di conferma</strong>. Ti contatteremo se serve.</p>
        </div>
        """
        risultati["cliente"] = invia_email(
            impostazioni,
            email_cliente,
            f"La tua prenotazione da {nome_attivita}: {servizio} il {data}",
            corpo_cliente,
            html_cliente,
        )
    elif not email_cliente:
        risultati["cliente"] = (False, "il cliente non ha lasciato email")

    return risultati
