"""Translations for UntitledLink.

UI chrome and status lines are translated. Log lines stay English on purpose:
they are diagnostics, and an English log is the one you can paste into a bug
report or search the web for.

Adding a language means adding one dict below. Missing keys fall back to
English rather than crashing, so a partial translation is usable.
"""

import re

# Only what is offered in the settings dropdown. STRINGS below still carries
# the Spanish and German translations - putting either back in front of the
# user is adding its code to this dict, nothing else.
LANGUAGES = {"en": "English", "el": "Ελληνικά"}

# Browsers yt-dlp can lift cookies from. "" means do not touch any of them.
# The first entry is "no cookies". It is a word rather than "" because an
# empty combobox reads as "nothing loaded yet", not as a choice you made.
NO_COOKIES = "none"
COOKIE_BROWSERS = [NO_COOKIES, "chrome", "firefox", "edge", "brave",
                   "opera", "vivaldi"]

STRINGS = {
    "en": {
        "scan": "scan", "clear": "clear", "refresh": "refresh",
        "download": "download", "stop": "stop",
        "settings": "settings", "log": "log", "copy_log": "copy log", "open": "open",
        "browse": "...", "save": "save", "cancel": "cancel",
        "quality": "quality", "save_to": "save to",
        "col_type": "TYPE", "col_size": "SIZE", "col_info": "INFO",
        "col_quality": "QUALITY", "col_length": "LENGTH", "col_res": "RESOLUTION",
        "source": "source",
        "dlg_private": "private session",
        "dlg_private_hint": "Leaves nothing on this computer: no settings file,\n"
                            "no crash file, and browser cookies stay untouched\n"
                            "so no site is told which account you are.\n"
                            "It does NOT hide the download from the site. Your\n"
                            "address is in their logs either way - only a proxy\n"
                            "changes that. Not remembered; switch it on each time.",
        "dlg_tor": "route everything through tor",
        "dlg_tor_hint": "Off by default, and not remembered. Sends every\n"
                        "request through Tor on 127.0.0.1:9050, so the site\n"
                        "sees an exit node and your provider sees Tor.\n"
                        "Tor has to be running: the Tor Browser, or the tor\n"
                        "service. Expect it to be slow, and expect some\n"
                        "sites to refuse an exit node outright. Turn browser\n"
                        "cookies off with it - a login says who you are\n"
                        "whatever address it arrives from.",
        "tor_missing": "tor is not running on 127.0.0.1:9050",
        "tor_private": "tor on :: private session on with it",
        "cookies_off_private": "Off while the private session is on: it leaves\n"
                               "the browser's cookies alone, so no site is told\n"
                               "which account is asking.",
        "proxy_ignored_tor": "Ignored while tor is on. Untick tor to use this\n"
                             "address instead.",
        "chip_private": "private",
        "chip_private_bare": "private (no proxy - your address still shows)",
        "chip_proxy": "proxy",
        "chip_tor": "tor",
        "chip_tor_cookies": "tor (cookies name you)",
        "chip_cookies": "cookies:{name}",
        "chip_strip": "metadata stripped",
        "chip_no_ffmpeg": "no ffmpeg",
        "tor_slow_scan": "tor on :: the discreet scan makes a page one request instead of fifty",
        "sec_download": "downloading",
        "sec_privacy": "privacy",
        "sec_window": "the window",
        "dlg_subs": "subtitles too, when there are any",
        "dlg_subs_hint": "Off by default. Saves the subtitles beside the\n"
                         "video in the window's language, then English -\n"
                         "both the written ones and the machine\n"
                         "transcript, since a lecture often has only the\n"
                         "second. As .srt, converted by the ffmpeg this\n"
                         "app carries, since sites hand out vtt as often\n"
                         "as srt. Beside the file rather than inside it,\n"
                         "so a text editor can open it.",
        "have_already": "already here",
        "dlg_folders": "a folder per page",
        "dlg_folders_hint": "Off by default. Files from one page land in a\n"
                            "folder named after it, instead of forty\n"
                            "handouts loose among everything else you have\n"
                            "ever downloaded. For a single video a folder\n"
                            "of its own is clutter, which is why it is off.",
        "dlg_route": "test the route",
        "route_checking": "asking...",
        "route_none": "no route set :: the site sees your own address",
        "route_tor": "tor :: the site sees {ip}",
        "route_proxy": "a proxy, but not tor :: the site sees {ip}",
        "route_failed": "the route did not answer :: {why}",
        "dlg_dblclick": "double click a row to download it",
        "dlg_dblclick_hint": "Off by default. The first click of the pair has\n"
                             "already marked the row, so an accidental double\n"
                             "click would start a download you did not ask for.",
        "dlg_quiet": "discreet scan",
        "dlg_quiet_hint": "On by default. The scan asks the site for the\n"
                          "page and nothing else: no size is measured and\n"
                          "no larger copy of an image is hunted for, so a\n"
                          "page of 20 links costs one request instead of\n"
                          "thirty-one. The SIZE column shows a dot until\n"
                          "you open a row, which measures that one.\n"
                          "Untick it to have everything measured up front:\n"
                          "sizes to sort by, and links that turn out to be\n"
                          "web pages dropped before you see them - at one\n"
                          "request per link, which a small server reads as\n"
                          "a scraper.",
        # What a row is. Format names - mp4, vp9, avc1, fps, kHz - are not
        # translated anywhere: they are what the format is called, not words.
        "kind_video": "video", "kind_audio": "audio", "kind_image": "image",
        "kind_doc": "document", "kind_archive": "archive", "kind_file": "file",
        "q_as_set": "as set", "q_original": "original", "q_audio": "audio",
        "col_name": "NAME",
        "ready": "ready :: tick a box to pick a row :: ctrl+a picks all",
        "preview_hint": "select a row\nto preview",
        "no_preview": "no preview\nfor this type",
        "loading": "loading...", "preview_failed": "preview failed",
        "paste_first": "paste a link first",
        # The status line while the link is being worked out. It used to
        # name yt-dlp, which is a tool the window has no business making
        # anyone read about.
        "scanning": "converting the link...",
        "scanning_n": "converting link {n} of {total}...",
        "downloads": "downloads",
        "close": "close",
        "clear_history": "clear the list",
        "history_cleared": "download history cleared",
        "dlg_history": "remember what was downloaded",
        "dlg_history_hint": "Off by default. Keeps the list of downloads\n"
                            "between sessions - when, what, how big, and\n"
                            "which folder it went to. Never where it came\n"
                            "from: a path finds your file again, a source\n"
                            "address only says which sites you visited.\n"
                            "Nothing is written while the private session\n"
                            "is on, and the last 200 are kept.",
        "col_when": "WHEN",
        "col_where": "FOLDER",
        "open_file": "open the file",
        "open_folder": "open the folder",
        "gone_from_disk": "that file is not there any more",
        "search": "search",
        "menu_open_page": "open the page it came from",
        "menu_copy_link": "copy the link",
        "menu_copy_name": "copy the name",
        "copied": "copied",
        "retry": "retry the failed",
        "filter_count": "{n} of {total}",
        "found": "{n} found :: tick the boxes, then download",
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
        "dlg_quality_hint": "Only used for playlists, and for pages that do not\n"
                            "list their formats. Everywhere else each resolution\n"
                            "is already a row of its own.",
        "dlg_parallel_hint": "More is faster until your connection is the limit.",
        "dlg_ffmpeg": "ffmpeg", "dlg_ffmpeg_missing": "not installed",
        "dlg_lang_note": "The window reloads when you change language.",
        "no_video": "{site} served no media here.",
        "try_cookies": "If it needs a login, turn on browser cookies in settings.",
    },
    "el": {
        "scan": "σάρωση", "clear": "καθαρισμός", "refresh": "ανανέωση",
        "download": "λήψη",
        "stop": "διακοπή", "settings": "ρυθμίσεις", "log": "αρχείο",
        "copy_log": "αντιγραφή", "open": "άνοιγμα", "browse": "...",
        "save": "αποθήκευση", "cancel": "άκυρο",
        "quality": "ποιότητα", "save_to": "αποθήκευση σε",
        "col_type": "ΤΥΠΟΣ", "col_size": "ΜΕΓΕΘΟΣ", "col_info": "ΣΤΟΙΧΕΙΑ",
        "col_quality": "ΠΟΙΟΤΗΤΑ", "col_length": "ΔΙΑΡΚΕΙΑ", "col_res": "ΑΝΑΛΥΣΗ",
        "source": "πηγή",
        "dlg_private": "ιδιωτική συνεδρία",
        "dlg_private_hint": "Δεν αφήνει τίποτα σε αυτόν τον υπολογιστή: ούτε αρχείο\n"
                            "ρυθμίσεων, ούτε crash, και δεν αγγίζει τα cookies του\n"
                            "browser - κανένα site δεν μαθαίνει ποιος λογαριασμός είσαι.\n"
                            "ΔΕΝ κρύβει τη λήψη από το site. Η διεύθυνσή σου είναι στα\n"
                            "logs του έτσι κι αλλιώς - μόνο ένα proxy το αλλάζει αυτό.\n"
                            "Δεν απομνημονεύεται· ενεργοποίησέ το κάθε φορά.",
        "dlg_tor": "όλα μέσα από tor",
        "dlg_tor_hint": "Ανενεργό εξ ορισμού, και δεν απομνημονεύεται.\n"
                        "Στέλνει κάθε αίτημα μέσα από το Tor στο\n"
                        "127.0.0.1:9050, οπότε το site βλέπει exit node και\n"
                        "ο πάροχός σου βλέπει Tor.\n"
                        "Το Tor πρέπει να τρέχει: ο Tor Browser ή η\n"
                        "υπηρεσία tor. Περίμενε αργά, και περίμενε κάποια\n"
                        "sites να αρνούνται τα exit nodes.\n"
                        "Κλείσε μαζί τα cookies - μια σύνδεση λέει ποιος\n"
                        "είσαι από όποια διεύθυνση κι αν έρθει.",
        "tor_missing": "το tor δεν τρέχει στο 127.0.0.1:9050",
        "tor_private": "tor ενεργό :: μαζί και ιδιωτική συνεδρία",
        "cookies_off_private": "Ανενεργά όσο τρέχει η ιδιωτική συνεδρία: δεν\n"
                               "αγγίζει τα cookies του browser, οπότε κανένα\n"
                               "site δεν μαθαίνει ποιος λογαριασμός ρωτάει.",
        "proxy_ignored_tor": "Αγνοείται όσο το tor είναι αναμμένο. Σβήσε το tor\n"
                             "για να χρησιμοποιηθεί αυτή η διεύθυνση.",
        "chip_private": "ιδιωτική",
        "chip_private_bare": "ιδιωτική (χωρίς proxy - η διεύθυνσή σου φαίνεται)",
        "chip_proxy": "proxy",
        "chip_tor": "tor",
        "chip_tor_cookies": "tor (τα cookies σε ονομάζουν)",
        "chip_cookies": "cookies:{name}",
        "chip_strip": "καθαρά metadata",
        "chip_no_ffmpeg": "χωρίς ffmpeg",
        "tor_slow_scan": "tor ενεργό :: με διακριτική σάρωση μια σελίδα κοστίζει ένα αίτημα αντί για πενήντα",
        "sec_download": "λήψη",
        "sec_privacy": "ιδιωτικότητα",
        "sec_window": "το παράθυρο",
        "dlg_subs": "και υπότιτλοι, όπου υπάρχουν",
        "dlg_subs_hint": "Ανενεργό εξ ορισμού. Αποθηκεύει τους υπότιτλους\n"
                         "δίπλα στο βίντεο, στη γλώσσα του παραθύρου και\n"
                         "μετά στα αγγλικά - και τους γραμμένους και την\n"
                         "αυτόματη απομαγνητοφώνηση, αφού μια διάλεξη\n"
                         "συχνά έχει μόνο τη δεύτερη. Σε .srt, με το ffmpeg\n"
                         "που ήδη κουβαλάει η εφαρμογή, γιατί τα sites\n"
                         "δίνουν vtt το ίδιο συχνά. Δίπλα στο αρχείο, όχι\n"
                         "μέσα του, ώστε να ανοίγει με επεξεργαστή κειμένου.",
        "have_already": "το έχεις ήδη",
        "dlg_folders": "φάκελος ανά σελίδα",
        "dlg_folders_hint": "Ανενεργό εξ ορισμού. Τα αρχεία μιας σελίδας\n"
                            "μπαίνουν σε φάκελο με το όνομά της, αντί για\n"
                            "σαράντα αρχεία χύμα ανάμεσα σε ό,τι έχεις\n"
                            "κατεβάσει ποτέ. Για ένα βίντεο, ξεχωριστός\n"
                            "φάκελος είναι σκουπίδι - γι' αυτό είναι σβηστό.",
        "dlg_route": "δοκιμή διαδρομής",
        "route_checking": "ρωτάω...",
        "route_none": "καμία διαδρομή :: το site βλέπει τη διεύθυνσή σου",
        "route_tor": "tor :: το site βλέπει {ip}",
        "route_proxy": "proxy, όχι tor :: το site βλέπει {ip}",
        "route_failed": "η διαδρομή δεν απάντησε :: {why}",
        "dlg_dblclick": "διπλό κλικ σε γραμμή για λήψη",
        "dlg_dblclick_hint": "Ανενεργό εξ ορισμού. Το πρώτο κλικ έχει ήδη\n"
                             "μαρκάρει τη γραμμή, οπότε ένα κατά λάθος διπλό\n"
                             "κλικ θα ξεκινούσε λήψη που δεν ζήτησες.",
        "dlg_quiet": "διακριτική σάρωση",
        "dlg_quiet_hint": "Ενεργό εξ ορισμού. Η σάρωση ζητά από το site τη\n"
                          "σελίδα και τίποτε άλλο: δεν μετριέται μέγεθος\n"
                          "και δεν αναζητείται μεγαλύτερη έκδοση εικόνας,\n"
                          "οπότε μια σελίδα με 20 links κοστίζει ένα αίτημα\n"
                          "αντί για τριάντα ένα. Η στήλη ΜΕΓΕΘΟΣ δείχνει\n"
                          "τελεία μέχρι να ανοίξεις μια γραμμή.\n"
                          "Σβήσ' το για να μετρηθούν όλα από την αρχή:\n"
                          "μεγέθη για ταξινόμηση, και links που τελικά είναι\n"
                          "σελίδες πετιούνται πριν τα δεις - με ένα αίτημα\n"
                          "ανά link, που ένας μικρός server το διαβάζει σαν\n"
                          "scraper.",
        "kind_video": "βίντεο", "kind_audio": "ήχος", "kind_image": "εικόνα",
        "kind_doc": "έγγραφο", "kind_archive": "αρχειοθήκη", "kind_file": "αρχείο",
        "q_as_set": "ό,τι ορίστηκε", "q_original": "πρωτότυπο", "q_audio": "ήχος",
        "dlg_quality_hint": "Χρησιμοποιείται μόνο σε playlist, και σε σελίδες\n"
                            "που δεν δίνουν λίστα φορμά. Παντού αλλού κάθε\n"
                            "ανάλυση είναι ήδη ξεχωριστή γραμμή.",
        "col_name": "ΟΝΟΜΑ",
        "ready": "έτοιμο :: τσέκαρε το κουτάκι για επιλογή :: ctrl+a για όλα",
        "preview_hint": "διάλεξε γραμμή\nγια προεπισκόπηση",
        "no_preview": "χωρίς προεπισκόπηση\nγια αυτόν τον τύπο",
        "loading": "φόρτωση...", "preview_failed": "η προεπισκόπηση απέτυχε",
        "paste_first": "βάλε πρώτα ένα λινκ",
        "scanning": "μετατροπή συνδέσμου...",
        "scanning_n": "μετατροπή συνδέσμου {n} από {total}...",
        "downloads": "λήψεις",
        "close": "κλείσιμο",
        "clear_history": "καθαρισμός λίστας",
        "history_cleared": "το ιστορικό λήψεων καθαρίστηκε",
        "dlg_history": "να θυμάται τι κατέβηκε",
        "dlg_history_hint": "Ανενεργό εξ ορισμού. Κρατά τη λίστα λήψεων\n"
                            "ανάμεσα στις συνεδρίες - πότε, τι, πόσο, και σε\n"
                            "ποιον φάκελο. Ποτέ από πού: η διαδρομή βρίσκει\n"
                            "ξανά το αρχείο σου, η διεύθυνση πηγής λέει μόνο\n"
                            "ποια sites επισκέφθηκες.\n"
                            "Δεν γράφεται τίποτα όσο τρέχει η ιδιωτική\n"
                            "συνεδρία, και κρατιούνται οι τελευταίες 200.",
        "col_when": "ΩΡΑ",
        "col_where": "ΦΑΚΕΛΟΣ",
        "open_file": "άνοιγμα αρχείου",
        "open_folder": "άνοιγμα φακέλου",
        "gone_from_disk": "το αρχείο δεν είναι πια εκεί",
        "search": "αναζήτηση",
        "menu_open_page": "άνοιγμα της σελίδας του",
        "menu_copy_link": "αντιγραφή συνδέσμου",
        "menu_copy_name": "αντιγραφή ονόματος",
        "copied": "αντιγράφηκε",
        "retry": "ξανά τα αποτυχημένα",
        "filter_count": "{n} από {total}",
        "found": "{n} βρέθηκαν :: τσέκαρε τα κουτάκια, μετά λήψη",
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
    },
    "es": {
        "scan": "escanear", "clear": "limpiar", "refresh": "recargar",
        "download": "descargar",
        "stop": "parar", "settings": "ajustes", "log": "registro",
        "copy_log": "copiar", "open": "abrir", "browse": "...",
        "save": "guardar", "cancel": "cancelar",
        "quality": "calidad", "save_to": "guardar en",
        "col_type": "TIPO", "col_size": "TAMAÑO", "col_info": "DATOS",
        "col_quality": "CALIDAD", "col_length": "DURACIÓN", "col_res": "RESOLUCIÓN",
        "source": "fuente",
        "dlg_private": "sesión privada",
        "dlg_private_hint": "No deja nada en este ordenador: ni archivo de ajustes,\n"
                            "ni archivo de fallos, y no toca las cookies del navegador.\n"
                            "NO oculta la descarga del sitio: tu dirección queda en sus\n"
                            "registros igualmente, solo un proxy cambia eso.\n"
                            "No se recuerda; actívala cada vez.",
        "dlg_dblclick": "doble clic en una fila para descargarla",
        "dlg_dblclick_hint": "Desactivado por defecto. El primer clic ya marca\n"
                             "la fila, así que un doble clic accidental\n"
                             "iniciaría una descarga que no pediste.",
        "kind_video": "vídeo", "kind_audio": "audio", "kind_image": "imagen",
        "kind_doc": "documento", "kind_archive": "archivo comprimido",
        "kind_file": "archivo",
        "q_as_set": "según ajustes", "q_original": "original", "q_audio": "audio",
        "dlg_quality_hint": "Solo se usa en listas de reproducción y en páginas\n"
                            "que no listan sus formatos. En el resto cada\n"
                            "resolución ya es su propia fila.",
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
    },
    "de": {
        "scan": "scannen", "clear": "leeren", "refresh": "neu laden",
        "download": "laden",
        "stop": "stopp", "settings": "einstellungen", "log": "protokoll",
        "copy_log": "kopieren", "open": "öffnen", "browse": "...",
        "save": "speichern", "cancel": "abbrechen",
        "quality": "qualität", "save_to": "speichern in",
        "col_type": "TYP", "col_size": "GRÖSSE", "col_info": "INFOS",
        "col_quality": "QUALITÄT", "col_length": "DAUER", "col_res": "AUFLÖSUNG",
        "source": "Quelle",
        "dlg_private": "private Sitzung",
        "dlg_private_hint": "Hinterlässt nichts auf diesem Rechner: keine Einstellungs-\n"
                            "datei, keine Absturzdatei, und die Browser-Cookies bleiben\n"
                            "unberührt. Verbirgt den Download NICHT vor der Seite - deine\n"
                            "Adresse steht so oder so in deren Logs, das ändert nur ein\n"
                            "Proxy. Wird nicht gemerkt; jedes Mal neu einschalten.",
        "dlg_dblclick": "Doppelklick auf eine Zeile lädt sie herunter",
        "dlg_dblclick_hint": "Standardmäßig aus. Der erste Klick markiert die\n"
                             "Zeile bereits, ein versehentlicher Doppelklick\n"
                             "würde also einen Download starten.",
        "kind_video": "Video", "kind_audio": "Audio", "kind_image": "Bild",
        "kind_doc": "Dokument", "kind_archive": "Archiv", "kind_file": "Datei",
        "q_as_set": "wie eingestellt", "q_original": "Original", "q_audio": "Audio",
        "dlg_quality_hint": "Wird nur für Playlists benutzt und für Seiten, die\n"
                            "keine Formatliste liefern. Sonst ist jede Auflösung\n"
                            "bereits eine eigene Zeile.",
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
    },
}


# Words that start a line in lowercase because that is their name, not because
# the sentence has not been capitalised yet.
KEEP_LOWER = {"ffmpeg", "iphone", "macos"}
_FIRST_WORD = re.compile(r"[\s:.,;()\[\]]")


class Tr:
    """Translator. A missing key falls back to English, never to a crash."""

    def __init__(self, lang="en"):
        self.set(lang)

    def set(self, lang):
        self.lang = lang if lang in STRINGS else "en"
        self.table = STRINGS[self.lang]

    def __call__(self, key, **kw):
        text = self.table.get(key) or STRINGS["en"].get(key)
        if text is None:
            return key          # a missing key shows its own name, untouched
        if kw:
            text = text.format(**kw)
        # Sentence case, once, for every language: the strings are written in
        # lowercase and the window wants a capital at the front. Only the first
        # character is touched, so ALL CAPS headings and every name inside the
        # line survive.
        if not text[:1].islower():
            return text
        # A line that opens with something the world spells in lowercase is
        # left alone: "socks5://..." and "yt-dlp" are not sentences, and
        # "Socks5://" is a wrong address rather than a capitalised one. The
        # digits and punctuation give most of them away; the rest are listed.
        first = _FIRST_WORD.split(text, 1)[0]
        if not first.isalpha() or first in KEEP_LOWER:
            return text
        return text[0].upper() + text[1:]
