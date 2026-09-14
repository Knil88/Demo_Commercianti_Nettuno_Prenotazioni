import hashlib
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "prenotazioni.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "nettuno2026"

IMPOSTAZIONI_COLUMNS = {
    "orario_apertura": "TEXT DEFAULT '09:00'",
    "orario_chiusura": "TEXT DEFAULT '19:00'",
    "pausa_inizio": "TEXT DEFAULT ''",
    "pausa_fine": "TEXT DEFAULT ''",
    "slot_minuti": "INTEGER DEFAULT 15",
    "smtp_host": "TEXT DEFAULT 'smtp.gmail.com'",
    "smtp_port": "INTEGER DEFAULT 587",
    "smtp_user": "TEXT DEFAULT ''",
    "smtp_password": "TEXT DEFAULT ''",
    "invia_email_cliente": "INTEGER DEFAULT 1",
    "admin_username": "TEXT DEFAULT 'admin'",
    "admin_password_hash": "TEXT DEFAULT ''",
}

ALLOWED_IMPOSTAZIONI = {
    "nome_attivita",
    "indirizzo",
    "telefono",
    "email",
    "logo_path",
    "colore_primario",
    "colore_secondario",
    "orario_apertura",
    "orario_chiusura",
    "pausa_inizio",
    "pausa_fine",
    "slot_minuti",
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_password",
    "invia_email_cliente",
    "admin_username",
    "admin_password_hash",
}


def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
    return f"{salt}${digest.hex()}"


def verify_password(password, stored):
    if not password or not stored or "$" not in str(stored):
        return False
    salt, _digest = str(stored).split("$", 1)
    candidato = hash_password(password, salt)
    if len(candidato) != len(str(stored)):
        return False
    return secrets.compare_digest(candidato, str(stored))


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_columns(conn):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(impostazioni)")}
    for name, spec in IMPOSTAZIONI_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE impostazioni ADD COLUMN {name} {spec}")


def init_db():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with get_connection() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS impostazioni (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_attivita TEXT DEFAULT 'La Mia Attività',
            indirizzo TEXT DEFAULT '', telefono TEXT DEFAULT '',
            email TEXT DEFAULT '', logo_path TEXT DEFAULT '',
            colore_primario TEXT DEFAULT '#1E3A5F',
            colore_secondario TEXT DEFAULT '#E94560',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS servizi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL, descrizione TEXT DEFAULT '',
            durata_minuti INTEGER DEFAULT 60, prezzo REAL DEFAULT 0.0,
            attivo INTEGER DEFAULT 1)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS prenotazioni (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_cliente TEXT NOT NULL, cognome_cliente TEXT DEFAULT '',
            telefono TEXT NOT NULL, email TEXT DEFAULT '',
            servizio_id INTEGER, data_prenotazione TEXT NOT NULL,
            ora_prenotazione TEXT NOT NULL, note TEXT DEFAULT '',
            stato TEXT DEFAULT 'in_attesa',
            creato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (servizio_id) REFERENCES servizi(id))"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            ruolo TEXT DEFAULT '',
            foto_path TEXT DEFAULT '',
            attivo INTEGER DEFAULT 1)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS staff_orari (
            staff_id INTEGER NOT NULL,
            weekday INTEGER NOT NULL,
            lavora INTEGER DEFAULT 1,
            ora_inizio TEXT DEFAULT '09:00',
            ora_fine TEXT DEFAULT '19:00',
            PRIMARY KEY (staff_id, weekday),
            FOREIGN KEY (staff_id) REFERENCES staff(id))"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS staff_assenze (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            FOREIGN KEY (staff_id) REFERENCES staff(id))"""
        )
        _ensure_columns(conn)
        pren_cols = {row[1] for row in conn.execute("PRAGMA table_info(prenotazioni)")}
        if "staff_id" not in pren_cols:
            conn.execute("ALTER TABLE prenotazioni ADD COLUMN staff_id INTEGER")
        conn.execute("UPDATE prenotazioni SET stato = 'confermato' WHERE stato = 'confermata'")
        if not conn.execute("SELECT id FROM impostazioni LIMIT 1").fetchone():
            conn.execute("INSERT INTO impostazioni (nome_attivita) VALUES (?)", ("La Mia Attività",))

        row = conn.execute("SELECT id, admin_password_hash FROM impostazioni ORDER BY id DESC LIMIT 1").fetchone()
        if row and not row["admin_password_hash"]:
            conn.execute(
                "UPDATE impostazioni SET admin_username = ?, admin_password_hash = ? WHERE id = ?",
                (DEFAULT_ADMIN_USERNAME, hash_password(DEFAULT_ADMIN_PASSWORD), row["id"]),
            )

        if conn.execute("SELECT COUNT(*) AS n FROM servizi").fetchone()["n"] == 0:
            seed = [
                ("Taglio Capelli", "Taglio classico o moderno, con shampoo e finish.", 45, 25.0),
                ("Piega", "Piega e styling su capelli medi o lunghi.", 60, 35.0),
                ("Colore", "Colorazione completa con posa e shampoo.", 120, 60.0),
                ("Trattamento", "Trattamento ricostruttivo per capelli danneggiati.", 90, 45.0),
            ]
            conn.executemany(
                "INSERT INTO servizi (nome, descrizione, durata_minuti, prezzo) VALUES (?, ?, ?, ?)",
                seed,
            )
        _seed_staff(conn)
        _seed_prodotto(conn)


GIORNI = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]


def _orari_default_rows(imp=None):
    if imp is None:
        imp = {}
        row = None
        try:
            with get_connection() as conn:
                row = conn.execute("SELECT * FROM impostazioni ORDER BY id DESC LIMIT 1").fetchone()
            if row:
                imp = dict(row)
        except Exception:
            pass
    inizio = imp.get("orario_apertura") or "09:00"
    fine = imp.get("orario_chiusura") or "19:00"
    return [
        {"weekday": d, "lavora": 0 if d == 6 else 1, "ora_inizio": inizio, "ora_fine": fine}
        for d in range(7)
    ]


def _inserisci_orari_default(conn, staff_id, imp=None):
    for r in _orari_default_rows(imp):
        conn.execute(
            """INSERT OR IGNORE INTO staff_orari (staff_id, weekday, lavora, ora_inizio, ora_fine)
               VALUES (?, ?, ?, ?, ?)""",
            (staff_id, r["weekday"], r["lavora"], r["ora_inizio"], r["ora_fine"]),
        )


def _seed_staff(conn):
    if conn.execute("SELECT COUNT(*) AS n FROM staff").fetchone()["n"] > 0:
        return
    imp_row = conn.execute("SELECT * FROM impostazioni ORDER BY id DESC LIMIT 1").fetchone()
    imp = dict(imp_row) if imp_row else {}
    membri = [
        ("Giulia Moretti", "Colorista", "uploads/staff_giulia.jpg"),
        ("Luca Bianchi", "Taglio uomo e barba", "uploads/staff_luca.jpg"),
        ("Martina Russo", "Stylist", "uploads/staff_martina.jpg"),
    ]
    for nome, ruolo, foto in membri:
        if not os.path.isfile(os.path.join(BASE_DIR, foto.replace("/", os.sep))):
            foto = ""
        conn.execute(
            "INSERT INTO staff (nome, ruolo, foto_path, attivo) VALUES (?, ?, ?, 1)",
            (nome, ruolo, foto),
        )
        sid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        _inserisci_orari_default(conn, sid, imp)


def _seed_prodotto(conn):
    """Solo su installazione vuota: branding da salone e agenda di esempio."""
    row = conn.execute("SELECT * FROM impostazioni ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return
    nome = (row["nome_attivita"] or "").strip()
    if nome in ("", "La Mia Attività"):
        logo = "uploads/logo_nettuno_emblema.jpg"
        if not os.path.isfile(os.path.join(BASE_DIR, logo.replace("/", os.sep))):
            logo = row["logo_path"] or ""
        conn.execute(
            """UPDATE impostazioni SET
               nome_attivita = ?, indirizzo = ?, telefono = ?,
               orario_apertura = ?, orario_chiusura = ?,
               pausa_inizio = ?, pausa_fine = ?, logo_path = ?
               WHERE id = ?""",
            (
                "Nettuno Salon",
                "Via del Mare 12, Nettuno (RM)",
                "06 1234 5678",
                "09:00",
                "19:00",
                "13:00",
                "14:00",
                logo,
                row["id"],
            ),
        )
    if conn.execute("SELECT COUNT(*) AS n FROM prenotazioni").fetchone()["n"] > 0:
        return
    servizi = {r["nome"]: r["id"] for r in conn.execute("SELECT id, nome FROM servizi")}
    taglio = servizi.get("Taglio Capelli")
    piega = servizi.get("Piega")
    colore = servizi.get("Colore")
    tratt = servizi.get("Trattamento")
    oggi = datetime.now()
    def giorno(delta):
        return (oggi + timedelta(days=delta)).strftime("%Y-%m-%d")
    esempi = [
        ("Giulia", "Bianchi", "333 111 2233", "giulia.bianchi@email.it", taglio, giorno(0), "10:00", "", "pagato"),
        ("Marco", "Rossi", "333 222 3344", "marco.rossi@email.it", piega, giorno(0), "11:00", "Capelli lunghi", "in_attesa"),
        ("Elena", "Conti", "333 333 4455", "", colore, giorno(0), "15:00", "", "confermato"),
        ("Luca", "Ferrari", "333 444 5566", "luca.ferrari@email.it", taglio, giorno(1), "09:30", "", "confermato"),
        ("Sara", "De Luca", "333 555 6677", "", tratt, giorno(1), "16:00", "Prima volta", "in_attesa"),
        ("Anna", "Greco", "333 666 7788", "anna.greco@email.it", piega, giorno(2), "10:30", "", "pagato"),
    ]
    for riga in esempi:
        if not riga[4]:
            continue
        conn.execute(
            """INSERT INTO prenotazioni
               (nome_cliente, cognome_cliente, telefono, email, servizio_id,
                data_prenotazione, ora_prenotazione, note, stato)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            riga,
        )


def get_impostazioni():
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM impostazioni ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return {
            "nome_attivita": "La Mia Attività",
            "colore_primario": "#1E3A5F",
            "colore_secondario": "#E94560",
            "orario_apertura": "09:00",
            "orario_chiusura": "19:00",
            "pausa_inizio": "",
            "pausa_fine": "",
            "slot_minuti": 15,
            "admin_username": DEFAULT_ADMIN_USERNAME,
        }
    data = dict(row)
    data.setdefault("orario_apertura", "09:00")
    data.setdefault("orario_chiusura", "19:00")
    data.setdefault("pausa_inizio", "")
    data.setdefault("pausa_fine", "")
    data.setdefault("slot_minuti", 15)
    data.setdefault("smtp_host", "smtp.gmail.com")
    data.setdefault("smtp_port", 587)
    data.setdefault("invia_email_cliente", 1)
    return data


def update_impostazioni(**kwargs):
    fields = {k: v for k, v in kwargs.items() if k in ALLOWED_IMPOSTAZIONI}
    if not fields:
        return
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM impostazioni ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            placeholders = ", ".join(fields.keys())
            qs = ", ".join("?" for _ in fields)
            conn.execute(
                f"INSERT INTO impostazioni ({placeholders}) VALUES ({qs})",
                tuple(fields.values()),
            )
            return
        assignments = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE impostazioni SET {assignments} WHERE id = ?",
            (*fields.values(), row["id"]),
        )


def verify_admin(username, password):
    imp = get_impostazioni()
    stored_user = (imp.get("admin_username") or DEFAULT_ADMIN_USERNAME).strip()
    if username.strip() != stored_user:
        return False
    return verify_password(password, imp.get("admin_password_hash") or "")


def get_servizi(includi_disattivi=False):
    with get_connection() as conn:
        if includi_disattivi:
            rows = conn.execute("SELECT * FROM servizi ORDER BY nome").fetchall()
        else:
            rows = conn.execute("SELECT * FROM servizi WHERE attivo = 1 ORDER BY nome").fetchall()
    return [dict(r) for r in rows]


def get_servizio(servizio_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM servizi WHERE id = ?", (servizio_id,)).fetchone()
    return dict(row) if row else None


def add_servizio(nome, descrizione, durata_minuti, prezzo):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO servizi (nome, descrizione, durata_minuti, prezzo) VALUES (?, ?, ?, ?)",
            (nome, descrizione or "", durata_minuti, prezzo),
        )


def update_servizio(servizio_id, nome, descrizione, durata_minuti, prezzo, attivo=1):
    with get_connection() as conn:
        conn.execute(
            """UPDATE servizi
               SET nome = ?, descrizione = ?, durata_minuti = ?, prezzo = ?, attivo = ?
               WHERE id = ?""",
            (nome, descrizione or "", durata_minuti, prezzo, 1 if attivo else 0, servizio_id),
        )


def add_prenotazione(nome, cognome, telefono, email, servizio_id, data, ora, note, stato="in_attesa", staff_id=None):
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO prenotazioni
               (nome_cliente, cognome_cliente, telefono, email, servizio_id,
                data_prenotazione, ora_prenotazione, note, stato, staff_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (nome, cognome or "", telefono, email or "", servizio_id, data, ora, note or "", stato, staff_id),
        )
        last_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return last_id


def get_prenotazione(prenotazione_id):
    with get_connection() as conn:
        row = conn.execute(
            """SELECT p.*, s.nome AS servizio_nome, s.descrizione AS servizio_descrizione,
                      s.durata_minuti, s.prezzo AS servizio_prezzo,
                      st.nome AS staff_nome, st.ruolo AS staff_ruolo, st.foto_path AS staff_foto
               FROM prenotazioni p
               LEFT JOIN servizi s ON p.servizio_id = s.id
               LEFT JOIN staff st ON p.staff_id = st.id
               WHERE p.id = ?""",
            (prenotazione_id,),
        ).fetchone()
    return dict(row) if row else None


def get_prenotazioni(data=None, stato=None):
    query = """SELECT p.*, s.nome AS servizio_nome, s.descrizione AS servizio_descrizione,
                      s.durata_minuti, s.prezzo AS servizio_prezzo,
                      st.nome AS staff_nome, st.ruolo AS staff_ruolo, st.foto_path AS staff_foto
               FROM prenotazioni p
               LEFT JOIN servizi s ON p.servizio_id = s.id
               LEFT JOIN staff st ON p.staff_id = st.id
               WHERE 1=1"""
    params = []
    if data:
        query += " AND p.data_prenotazione = ?"
        params.append(data)
    if stato:
        query += " AND p.stato = ?"
        params.append(stato)
    query += " ORDER BY p.data_prenotazione, p.ora_prenotazione"
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def update_stato_prenotazione(prenotazione_id, stato):
    with get_connection() as conn:
        conn.execute("UPDATE prenotazioni SET stato = ? WHERE id = ?", (stato, prenotazione_id))


def update_prenotazione_staff(prenotazione_id, staff_id):
    with get_connection() as conn:
        conn.execute("UPDATE prenotazioni SET staff_id = ? WHERE id = ?", (staff_id, prenotazione_id))


def get_staff(includi_inattivi=False):
    with get_connection() as conn:
        if includi_inattivi:
            rows = conn.execute("SELECT * FROM staff ORDER BY nome").fetchall()
        else:
            rows = conn.execute("SELECT * FROM staff WHERE attivo = 1 ORDER BY nome").fetchall()
    return [dict(r) for r in rows]


def get_membro(staff_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM staff WHERE id = ?", (staff_id,)).fetchone()
    return dict(row) if row else None


def add_staff(nome, ruolo="", foto_path=""):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO staff (nome, ruolo, foto_path, attivo) VALUES (?, ?, ?, 1)",
            (nome, ruolo or "", foto_path or ""),
        )
        sid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        _inserisci_orari_default(conn, sid, get_impostazioni())
    return sid


def update_staff(staff_id, nome, ruolo, foto_path, attivo=1):
    with get_connection() as conn:
        conn.execute(
            "UPDATE staff SET nome = ?, ruolo = ?, foto_path = ?, attivo = ? WHERE id = ?",
            (nome, ruolo or "", foto_path or "", 1 if attivo else 0, staff_id),
        )


def get_staff_orari(staff_id):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM staff_orari WHERE staff_id = ? ORDER BY weekday",
            (staff_id,),
        ).fetchall()
    found = {r["weekday"]: dict(r) for r in rows}
    out = []
    defaults = _orari_default_rows(get_impostazioni())
    for d in range(7):
        if d in found:
            out.append(found[d])
        else:
            row = defaults[d]
            row["staff_id"] = staff_id
            out.append(row)
    return out


def set_staff_orari(staff_id, orari):
    with get_connection() as conn:
        for r in orari:
            conn.execute(
                """INSERT INTO staff_orari (staff_id, weekday, lavora, ora_inizio, ora_fine)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(staff_id, weekday) DO UPDATE SET
                     lavora = excluded.lavora,
                     ora_inizio = excluded.ora_inizio,
                     ora_fine = excluded.ora_fine""",
                (
                    staff_id,
                    int(r["weekday"]),
                    1 if r.get("lavora") else 0,
                    r.get("ora_inizio") or "09:00",
                    r.get("ora_fine") or "19:00",
                ),
            )


def get_assenze(staff_id, da_data=None):
    query = "SELECT * FROM staff_assenze WHERE staff_id = ?"
    params = [staff_id]
    if da_data:
        query += " AND data >= ?"
        params.append(da_data)
    query += " ORDER BY data"
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def add_assenza(staff_id, data):
    with get_connection() as conn:
        esiste = conn.execute(
            "SELECT id FROM staff_assenze WHERE staff_id = ? AND data = ?",
            (staff_id, data),
        ).fetchone()
        if esiste:
            return esiste["id"]
        conn.execute(
            "INSERT INTO staff_assenze (staff_id, data) VALUES (?, ?)",
            (staff_id, data),
        )


def remove_assenza(assenza_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM staff_assenze WHERE id = ?", (assenza_id,))


def staff_lavorabile(staff_id, data):
    membro = get_membro(staff_id)
    if not membro or not membro.get("attivo"):
        return False
    with get_connection() as conn:
        assente = conn.execute(
            "SELECT id FROM staff_assenze WHERE staff_id = ? AND data = ?",
            (staff_id, data),
        ).fetchone()
    if assente:
        return False
    try:
        weekday = datetime.strptime(data, "%Y-%m-%d").weekday()
    except ValueError:
        return False
    orari = {r["weekday"]: r for r in get_staff_orari(staff_id)}
    giorno = orari.get(weekday)
    if not giorno or not giorno.get("lavora"):
        return False
    return True


def cancella_prenotazione(prenotazione_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM prenotazioni WHERE id = ?", (prenotazione_id,))


def get_statistiche():
    oggi = datetime.now().strftime("%Y-%m-%d")
    mese = datetime.now().strftime("%Y-%m")
    with get_connection() as conn:
        totale = conn.execute(
            "SELECT COUNT(*) AS n FROM prenotazioni WHERE stato != 'annullata'"
        ).fetchone()["n"]
        oggi_n = conn.execute(
            """SELECT COUNT(*) AS n FROM prenotazioni
               WHERE data_prenotazione = ? AND stato != 'annullata'""",
            (oggi,),
        ).fetchone()["n"]
        mese_n = conn.execute(
            """SELECT COUNT(*) AS n FROM prenotazioni
               WHERE strftime('%Y-%m', data_prenotazione) = ? AND stato != 'annullata'""",
            (mese,),
        ).fetchone()["n"]
        ricavi_row = conn.execute(
            """SELECT SUM(s.prezzo) AS totale
               FROM prenotazioni p
               LEFT JOIN servizi s ON p.servizio_id = s.id
               WHERE strftime('%Y-%m', p.data_prenotazione) = ?
                 AND p.stato = 'pagato'""",
            (mese,),
        ).fetchone()
        ricavi = ricavi_row["totale"] if ricavi_row and ricavi_row["totale"] else 0
    return {
        "totale_prenotazioni": totale,
        "prenotazioni_oggi": oggi_n,
        "prenotazioni_mese": mese_n,
        "ricavi_mese": ricavi,
    }


def _hhmm_to_min(value):
    parts = str(value).strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _min_to_hhmm(minutes):
    minutes = max(0, minutes) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _sovrappone(inizio_a, fine_a, inizio_b, fine_b):
    return inizio_a < fine_b and inizio_b < fine_a


def pausa_range(imp=None):
    """Restituisce (inizio, fine) in minuti, o None se il negozio non ha pausa."""
    if imp is None:
        imp = get_impostazioni()
    inizio = (imp.get("pausa_inizio") or "").strip()
    fine = (imp.get("pausa_fine") or "").strip()
    if not inizio or not fine:
        return None
    try:
        a = _hhmm_to_min(inizio)
        b = _hhmm_to_min(fine)
    except (TypeError, ValueError, IndexError):
        return None
    if b <= a:
        return None
    return a, b


def _fascia_staff(staff_id, data, imp=None):
    """Intersezione orario negozio + orario della persona quel giorno."""
    if imp is None:
        imp = get_impostazioni()
    if not staff_lavorabile(staff_id, data):
        return None
    weekday = datetime.strptime(data, "%Y-%m-%d").weekday()
    giorno = next((r for r in get_staff_orari(staff_id) if r["weekday"] == weekday), None)
    if not giorno:
        return None
    try:
        shop_a = _hhmm_to_min(imp.get("orario_apertura") or "09:00")
        shop_c = _hhmm_to_min(imp.get("orario_chiusura") or "19:00")
        staff_a = _hhmm_to_min(giorno.get("ora_inizio") or "09:00")
        staff_c = _hhmm_to_min(giorno.get("ora_fine") or "19:00")
    except (TypeError, ValueError, IndexError):
        return None
    inizio = max(shop_a, staff_a)
    fine = min(shop_c, staff_c)
    if fine <= inizio:
        return None
    return inizio, fine


def slot_occupato(data, ora, servizio_id, exclude_id=None, staff_id=None):
    servizio = get_servizio(servizio_id)
    durata = int(servizio["durata_minuti"]) if servizio else 60
    nuovo_start = _hhmm_to_min(ora)
    nuovo_end = nuovo_start + durata
    pausa = pausa_range()
    if pausa and _sovrappone(nuovo_start, nuovo_end, pausa[0], pausa[1]):
        return True
    if staff_id:
        fascia = _fascia_staff(staff_id, data)
        if not fascia or nuovo_start < fascia[0] or nuovo_end > fascia[1]:
            return True
    prenotazioni = get_prenotazioni(data=data)
    for p in prenotazioni:
        if p["stato"] == "annullata":
            continue
        if exclude_id is not None and p["id"] == exclude_id:
            continue
        if staff_id:
            if p.get("staff_id") != staff_id:
                continue
        start = _hhmm_to_min(p["ora_prenotazione"])
        end = start + int(p.get("durata_minuti") or 60)
        if _sovrappone(nuovo_start, nuovo_end, start, end):
            return True
    return False


def get_slot_disponibili(data, servizio_id, staff_id=None):
    servizio = get_servizio(servizio_id)
    if not servizio:
        return []
    imp = get_impostazioni()
    try:
        passo = int(imp.get("slot_minuti") or 15)
    except (TypeError, ValueError):
        passo = 15
    if passo <= 0:
        passo = 15
    durata = int(servizio["durata_minuti"] or 60)
    oggi = datetime.now().strftime("%Y-%m-%d")
    adesso = datetime.now().hour * 60 + datetime.now().minute
    if staff_id:
        fascia = _fascia_staff(staff_id, data, imp)
        if not fascia:
            return []
        apertura, chiusura = fascia
        staff_filter = staff_id
    else:
        try:
            apertura = _hhmm_to_min(imp.get("orario_apertura") or "09:00")
            chiusura = _hhmm_to_min(imp.get("orario_chiusura") or "19:00")
        except (TypeError, ValueError):
            apertura, chiusura = 9 * 60, 19 * 60
        staff_filter = None
    occupati = []
    pausa = pausa_range(imp)
    if pausa:
        occupati.append(pausa)
    for p in get_prenotazioni(data=data):
        if p["stato"] == "annullata":
            continue
        if staff_filter and p.get("staff_id") != staff_filter:
            continue
        start = _hhmm_to_min(p["ora_prenotazione"])
        occupati.append((start, start + int(p.get("durata_minuti") or 60)))
    slot = []
    t = apertura
    while t + durata <= chiusura:
        if data == oggi and t < adesso + 10:
            t += passo
            continue
        nuovo_end = t + durata
        if any(_sovrappone(t, nuovo_end, inizio, fine) for inizio, fine in occupati):
            t += passo
            continue
        slot.append(_min_to_hhmm(t))
        t += passo
    return slot
