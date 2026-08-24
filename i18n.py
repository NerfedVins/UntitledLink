"""Translations for convertex.

UI chrome and status lines are translated. Log lines stay English on purpose:
they are diagnostics, and an English log is the one you can paste into a bug
report or search the web for.

Adding a language means adding one dict below. Missing keys fall back to
English rather than crashing, so a partial translation is usable.
"""

LANGUAGES = {"en": "English", "el": "Ελληνικά", "es": "Español", "de": "Deutsch"}

# Browsers yt-dlp can lift cookies from. "" means do not touch any of them.
COOKIE_BROWSERS = ["", "chrome", "firefox", "edge", "brave", "opera", "vivaldi"]

STRINGS = {
    "en": {
        "tagline": "paste a link, take what you want",
        "scan": "scan", "clear": "clear", "refresh": "refresh",
        "download": "download", "stop": "stop",
        "settings": "settings", "log": "log", "copy_log": "copy log", "open": "open",
        "browse": "...", "get_ffmpeg": "get ffmpeg", "save": "save", "cancel": "cancel",
        "quality": "quality", "save_to": "save to",
        "col_type": "TYPE", "col_size": "SIZE", "col_info": "INFO",
        "col_name": "NAME",
        "ready": "ready :: click a row to mark it :: ctrl+a marks all",
        "preview_hint": "select a row\nto preview",
        "no_preview": "no preview\nfor this type",
        "loading": "loading...", "preview_failed": "preview failed",
        "paste_first": "paste a link first",
        "found": "{n} found :: click rows to mark, then download",
        "nothing_found": "nothing downloadable found here",
        "scan_failed": "scan failed :: {err}",
        "marked": "{n} marked :: {size} total",
        "nothing_marked": "nothing marked :: download would take every row",
        "nothing_to_dl": "nothing to download - scan a link first",
        "done": "done :: {ok} saved{tail} :: {dir}",
        "failed_tail": ", {n} failed - see log",
        "cancelled_tail": ", {n} cancelled",
        "pulled": "pulled from queue :: {n} cancelled",
        "stopping": "stopping...",
        "cut": "Cut", "copy": "Copy", "paste": "Paste", "select_all": "Select all",
        "log_copied": "log copied to clipboard",
        "dlg_title": "settings", "dlg_language": "language", "dlg_proxy": "proxy",
        "dlg_proxy_hint": "socks5://127.0.0.1:9050 for Tor, or any VPN endpoint.\n"
                          "Empty means the site sees your real IP.",
        "dlg_strip": "strip metadata from downloads",
        "dlg_strip_hint": "Removes EXIF, container tags and the Windows source marker.",
        "dlg_cookies": "use cookies from",
        "dlg_cookies_hint": "Needed for login-walled X, Instagram, private playlists.\n"
                            "WARNING: this identifies you to the site as your account.",
        "dlg_attempts": "tries per file",
        "dlg_parallel": "downloads at once",
        "dlg_parallel_hint": "More is faster until your connection is the limit.",
        "dlg_ffmpeg": "ffmpeg", "dlg_ffmpeg_missing": "not installed",
        "dlg_lang_note": "The window reloads when you change language.",
        "no_video": "{site} served no media here.",
        "try_cookies": "If it needs a login, turn on browser cookies in settings.",
        "ffmpeg_ready": "ffmpeg ready :: rescan to see every resolution",
        "ffmpeg_failed": "ffmpeg download failed :: {err}",
        "ffmpeg_dl": "downloading ffmpeg...",
    },
    "el": {
        "tagline": "βάλε ένα λινκ, πάρε ό,τι θέλεις",
        "scan": "σάρωση", "clear": "καθαρισμός", "refresh": "ανανέωση",
        "download": "λήψη",
        "stop": "διακοπή", "settings": "ρυθμίσεις", "log": "αρχείο",
        "copy_log": "αντιγραφή", "open": "άνοιγμα", "browse": "...",
        "get_ffmpeg": "λήψη ffmpeg", "save": "αποθήκευση", "cancel": "άκυρο",
        "quality": "ποιότητα", "save_to": "αποθήκευση σε",
        "col_type": "ΤΥΠΟΣ", "col_size": "ΜΕΓΕΘΟΣ", "col_info": "ΣΤΟΙΧΕΙΑ",
        "col_name": "ΟΝΟΜΑ",
        "ready": "έτοιμο :: κλικ σε γραμμή για μαρκάρισμα :: ctrl+a για όλα",
        "preview_hint": "διάλεξε γραμμή\nγια προεπισκόπηση",
        "no_preview": "χωρίς προεπισκόπηση\nγια αυτόν τον τύπο",
        "loading": "φόρτωση...", "preview_failed": "η προεπισκόπηση απέτυχε",
        "paste_first": "βάλε πρώτα ένα λινκ",
        "found": "{n} βρέθηκαν :: κλικ για μαρκάρισμα, μετά λήψη",
        "nothing_found": "δεν βρέθηκε τίποτα για κατέβασμα εδώ",
        "scan_failed": "η σάρωση απέτυχε :: {err}",
        "marked": "{n} μαρκαρισμένα :: {size} σύνολο",
        "nothing_marked": "κανένα μαρκαρισμένο :: η λήψη θα πάρει όλες τις γραμμές",
        "nothing_to_dl": "τίποτα για λήψη - σάρωσε πρώτα ένα λινκ",
        "done": "τέλος :: {ok} αποθηκεύτηκαν{tail} :: {dir}",
        "failed_tail": ", {n} απέτυχαν - δες το αρχείο",
        "cancelled_tail": ", {n} ακυρώθηκαν",
        "pulled": "βγήκε από την ουρά :: {n} ακυρωμένα",
        "stopping": "διακοπή...",
        "cut": "Αποκοπή", "copy": "Αντιγραφή", "paste": "Επικόλληση",
        "select_all": "Επιλογή όλων", "log_copied": "το αρχείο αντιγράφηκε",
        "dlg_title": "ρυθμίσεις", "dlg_language": "γλώσσα", "dlg_proxy": "proxy",
        "dlg_proxy_hint": "socks5://127.0.0.1:9050 για Tor, ή οποιοδήποτε VPN.\n"
                          "Κενό σημαίνει ότι το site βλέπει την πραγματική σου IP.",
        "dlg_strip": "αφαίρεση metadata από τις λήψεις",
        "dlg_strip_hint": "Αφαιρεί EXIF, tags και τον δείκτη προέλευσης των Windows.",
        "dlg_cookies": "cookies από",
        "dlg_cookies_hint": "Χρειάζεται για κλειδωμένα X, Instagram, ιδιωτικές playlists.\n"
                            "ΠΡΟΣΟΧΗ: σε ταυτοποιεί στο site ως τον λογαριασμό σου.",
        "dlg_attempts": "προσπάθειες ανά αρχείο",
        "dlg_parallel": "ταυτόχρονες λήψεις",
        "dlg_parallel_hint": "Περισσότερες = πιο γρήγορα, μέχρι να φτάσει η γραμμή σου στο όριο.",
        "dlg_ffmpeg": "ffmpeg", "dlg_ffmpeg_missing": "δεν είναι εγκατεστημένο",
        "dlg_lang_note": "Το παράθυρο φορτώνει ξανά όταν αλλάξεις γλώσσα.",
        "no_video": "Το {site} δεν έδωσε τίποτα εδώ.",
        "try_cookies": "Αν θέλει σύνδεση, ενεργοποίησε τα cookies στις ρυθμίσεις.",
        "ffmpeg_ready": "το ffmpeg είναι έτοιμο :: κάνε ξανά σάρωση για όλες τις αναλύσεις",
        "ffmpeg_failed": "η λήψη του ffmpeg απέτυχε :: {err}",
        "ffmpeg_dl": "λήψη ffmpeg...",
    },
    "es": {
        "tagline": "pega un enlace, toma lo que quieras",
        "scan": "escanear", "clear": "limpiar", "refresh": "recargar",
        "download": "descargar",
        "stop": "parar", "settings": "ajustes", "log": "registro",
        "copy_log": "copiar", "open": "abrir", "browse": "...",
        "get_ffmpeg": "obtener ffmpeg", "save": "guardar", "cancel": "cancelar",
        "quality": "calidad", "save_to": "guardar en",
        "col_type": "TIPO", "col_size": "TAMAÑO", "col_info": "DATOS",
        "col_name": "NOMBRE",
        "ready": "listo :: clic en una fila para marcarla :: ctrl+a marca todas",
        "preview_hint": "elige una fila\npara la vista previa",
        "no_preview": "sin vista previa\npara este tipo",
        "loading": "cargando...", "preview_failed": "vista previa fallida",
        "paste_first": "pega un enlace primero",
        "found": "{n} encontrados :: marca filas y descarga",
        "nothing_found": "no hay nada descargable aquí",
        "scan_failed": "escaneo fallido :: {err}",
        "marked": "{n} marcados :: {size} en total",
        "nothing_marked": "nada marcado :: la descarga tomaría todas las filas",
        "nothing_to_dl": "nada que descargar - escanea un enlace primero",
        "done": "listo :: {ok} guardados{tail} :: {dir}",
        "failed_tail": ", {n} fallidos - ver registro",
        "cancelled_tail": ", {n} cancelados",
        "pulled": "sacado de la cola :: {n} cancelados",
        "stopping": "parando...",
        "cut": "Cortar", "copy": "Copiar", "paste": "Pegar",
        "select_all": "Seleccionar todo", "log_copied": "registro copiado",
        "dlg_title": "ajustes", "dlg_language": "idioma", "dlg_proxy": "proxy",
        "dlg_proxy_hint": "socks5://127.0.0.1:9050 para Tor, o cualquier VPN.\n"
                          "Vacío significa que el sitio ve tu IP real.",
        "dlg_strip": "quitar metadatos de las descargas",
        "dlg_strip_hint": "Quita EXIF, etiquetas del contenedor y la marca de origen.",
        "dlg_cookies": "cookies de",
        "dlg_cookies_hint": "Necesario para X con login, Instagram y listas privadas.\n"
                            "AVISO: esto te identifica ante el sitio como tu cuenta.",
        "dlg_attempts": "intentos por archivo",
        "dlg_parallel": "descargas a la vez",
        "dlg_parallel_hint": "Más es más rápido hasta que tu conexión sea el límite.",
        "dlg_ffmpeg": "ffmpeg", "dlg_ffmpeg_missing": "no instalado",
        "dlg_lang_note": "La ventana se recarga al cambiar de idioma.",
        "no_video": "{site} no dio nada aquí.",
        "try_cookies": "Si requiere login, activa las cookies del navegador en ajustes.",
        "ffmpeg_ready": "ffmpeg listo :: vuelve a escanear para ver todas las resoluciones",
        "ffmpeg_failed": "descarga de ffmpeg fallida :: {err}",
        "ffmpeg_dl": "descargando ffmpeg...",
    },
    "de": {
        "tagline": "Link einfügen, nehmen was du willst",
        "scan": "scannen", "clear": "leeren", "refresh": "neu laden",
        "download": "laden",
        "stop": "stopp", "settings": "einstellungen", "log": "protokoll",
        "copy_log": "kopieren", "open": "öffnen", "browse": "...",
        "get_ffmpeg": "ffmpeg holen", "save": "speichern", "cancel": "abbrechen",
        "quality": "qualität", "save_to": "speichern in",
        "col_type": "TYP", "col_size": "GRÖSSE", "col_info": "INFOS",
        "col_name": "NAME",
        "ready": "bereit :: Zeile anklicken zum Markieren :: ctrl+a markiert alle",
        "preview_hint": "Zeile wählen\nfür Vorschau",
        "no_preview": "keine Vorschau\nfür diesen Typ",
        "loading": "lade...", "preview_failed": "Vorschau fehlgeschlagen",
        "paste_first": "erst einen Link einfügen",
        "found": "{n} gefunden :: Zeilen markieren, dann laden",
        "nothing_found": "hier ist nichts ladbar",
        "scan_failed": "Scan fehlgeschlagen :: {err}",
        "marked": "{n} markiert :: {size} gesamt",
        "nothing_marked": "nichts markiert :: Download nimmt alle Zeilen",
        "nothing_to_dl": "nichts zu laden - erst einen Link scannen",
        "done": "fertig :: {ok} gespeichert{tail} :: {dir}",
        "failed_tail": ", {n} fehlgeschlagen - siehe Protokoll",
        "cancelled_tail": ", {n} abgebrochen",
        "pulled": "aus der Warteschlange :: {n} abgebrochen",
        "stopping": "stoppe...",
        "cut": "Ausschneiden", "copy": "Kopieren", "paste": "Einfügen",
        "select_all": "Alles auswählen", "log_copied": "Protokoll kopiert",
        "dlg_title": "einstellungen", "dlg_language": "sprache", "dlg_proxy": "proxy",
        "dlg_proxy_hint": "socks5://127.0.0.1:9050 für Tor, oder ein VPN.\n"
                          "Leer heisst, die Seite sieht deine echte IP.",
        "dlg_strip": "Metadaten aus Downloads entfernen",
        "dlg_strip_hint": "Entfernt EXIF, Container-Tags und die Windows-Herkunftsmarke.",
        "dlg_cookies": "Cookies von",
        "dlg_cookies_hint": "Nötig für gesperrtes X, Instagram und private Playlists.\n"
                            "WARNUNG: das identifiziert dich als dein Konto.",
        "dlg_attempts": "Versuche pro Datei",
        "dlg_parallel": "gleichzeitige Downloads",
        "dlg_parallel_hint": "Mehr ist schneller, bis deine Leitung das Limit ist.",
        "dlg_ffmpeg": "ffmpeg", "dlg_ffmpeg_missing": "nicht installiert",
        "dlg_lang_note": "Das Fenster lädt neu, wenn du die Sprache änderst.",
        "no_video": "{site} lieferte hier nichts.",
        "try_cookies": "Braucht es einen Login, aktiviere Browser-Cookies in den Einstellungen.",
        "ffmpeg_ready": "ffmpeg bereit :: neu scannen für alle Auflösungen",
        "ffmpeg_failed": "ffmpeg-Download fehlgeschlagen :: {err}",
        "ffmpeg_dl": "lade ffmpeg...",
    },
}


class Tr:
    """Translator. A missing key falls back to English, never to a crash."""

    def __init__(self, lang="en"):
        self.set(lang)

    def set(self, lang):
        self.lang = lang if lang in STRINGS else "en"
        self.table = STRINGS[self.lang]

    def __call__(self, key, **kw):
        text = self.table.get(key) or STRINGS["en"].get(key) or key
        return text.format(**kw) if kw else text
