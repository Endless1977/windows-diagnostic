import customtkinter as ctk
import psutil
import platform
import requests
import threading
import re
import os
import subprocess
import tempfile
import shutil
import webbrowser
import time

# --- CONFIGURATIE ---
# Primaire engine: Ollama (gratis, lokaal, geen account, geen internet nodig
# tijdens gebruik). Als Ollama niet gevonden wordt, biedt het programma aan
# om deze automatisch te downloaden en installeren.
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "llama3.2"
OLLAMA_INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"
OLLAMA_DOWNLOAD_PAGE = "https://ollama.com/download"
OLLAMA_EXE_PAD = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")

# Fallback (als Ollama niet beschikbaar is/wordt): gratis, sleutelloze
# lokale analyse + DuckDuckGo-opzoeking. Zie DIAGNOSEKENNISBANK verderop.
DUCKDUCKGO_URL = "https://api.duckduckgo.com/"

if platform.system() == "Windows":
    import win32evtlog

# --- DIAGNOSEKENNISBANK ---
# Vaste, betrouwbare uitleg + oplossing per veelvoorkomende Windows EventID.
# Dit vervangt een "vrij pratende" AI door voorspelbare, altijd-werkende logica.
EVENTID_KENNISBANK = {
    "41": {
        "diagnose": "Het systeem is onverwacht herstart of afgesloten (bijv. door een stroomstoring, oververhitting, of een crash), zonder netjes af te sluiten.",
        "stappenplan": "Ga naar Instellingen -> Systeem -> Energie en accu, en controleer de energie-instellingen. Controleer ook of de pc niet oververhit raakt (stofvrij houden, ventilatie checken). Bij herhaling: controleer het geheugen via 'Windows Geheugendiagnose' (typ dit in de Startmenu-zoekbalk)."
    },
    "1000": {
        "diagnose": "Een programma is onverwacht vastgelopen (application crash).",
        "stappenplan": "Ga naar Instellingen -> Apps -> Geïnstalleerde apps en controleer of het genoemde programma up-to-date is, of installeer het opnieuw. Check ook Windows Update via Instellingen -> Windows Update."
    },
    "6008": {
        "diagnose": "De vorige systeemafsluiting was onverwacht (niet netjes afgesloten).",
        "stappenplan": "Sluit Windows voortaan altijd af via Start -> Aan/uit -> Afsluiten in plaats van de stroom eraf te halen. Controleer de voeding en kabel-verbindingen bij een desktop-pc."
    },
    "7000": {
        "diagnose": "Een Windows-service kon niet starten bij het opstarten.",
        "stappenplan": "Ga naar Start -> typ 'services.msc' -> zoek de genoemde service op -> rechtermuisklik -> Eigenschappen -> zet Opstarttype op 'Automatisch' en klik op Start."
    },
    "7001": {
        "diagnose": "Een service kon niet starten omdat een andere service waarvan hij afhankelijk is, niet actief is.",
        "stappenplan": "Ga naar Start -> typ 'services.msc' en controleer of gerelateerde Windows-services actief staan. Een herstart van de pc lost dit vaak op."
    },
    "10016": {
        "diagnose": "Een DCOM-onderdeel had niet de juiste rechten (dit is meestal onschuldig en komt vaak voor).",
        "stappenplan": "Dit veroorzaakt meestal geen merkbare problemen en kan in de praktijk genegeerd worden. Wil je het toch oplossen: ga naar Uitvoeren (Win+R) -> typ 'dcomcnfg' -> Onderdelenservices -> Computers -> Deze computer -> DCOM-configuratie, en pas de rechten aan van het genoemde onderdeel."
    },
    "erofs": {
        "diagnose": "Er is een schijf- of bestandssysteemfout gevonden.",
        "stappenplan": "Ga naar Deze pc -> rechtermuisklik op de C-schijf -> Eigenschappen -> Extra -> Nu controleren, om Windows de schijf te laten controleren op fouten."
    },
}

def zoek_duckduckgo_uitleg(zoekterm):
    """Zoekt een korte, gratis, sleutelloze uitleg op via de DuckDuckGo
    Instant Answer API. Geeft None terug als er niets bruikbaars gevonden is."""
    try:
        params = {
            "q": zoekterm,
            "format": "json",
            "no_html": 1,
            "skip_disambig": 1,
        }
        resp = requests.get(DUCKDUCKGO_URL, params=params, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            tekst = data.get("AbstractText", "").strip()
            if tekst:
                return tekst
            # Val terug op de eerste "gerelateerde" korte uitleg, indien aanwezig
            related = data.get("RelatedTopics", [])
            for item in related:
                if isinstance(item, dict) and item.get("Text"):
                    return item["Text"].strip()
    except Exception:
        pass
    return None

def is_ollama_bereikbaar():
    """Controleert of Ollama al actief draait en reageert."""
    try:
        r = requests.get("http://localhost:11434", timeout=2)
        return r.status_code == 200
    except Exception:
        return False

def is_ollama_geinstalleerd():
    """Controleert of het Ollama-programma op deze pc staat, ongeacht of het nu draait."""
    if shutil.which("ollama"):
        return True
    return os.path.exists(OLLAMA_EXE_PAD)

def bouw_lokaal_rapport(data):
    """Gratis, sleutelloze fallback-analyse (kennisbank + DuckDuckGo), gebruikt
    wanneer Ollama niet beschikbaar is of geen antwoord geeft."""
    if data["cpu_load"] >= 80:
        cpu_status = f"CPU-belasting is HOOG ({data['cpu_load']}%) - dit vertraagt merkbaar het systeem."
    elif data["cpu_load"] >= 50:
        cpu_status = f"CPU-belasting is MATIG ({data['cpu_load']}%) - houd dit in de gaten."
    else:
        cpu_status = f"CPU-belasting is NORMAAL ({data['cpu_load']}%)."

    if data["ram_percent"] >= 85:
        ram_status = f"RAM-gebruik is KRITIEK HOOG ({data['ram_percent']}%, {data['ram_used']}GB/{data['ram_total']}GB) - dit veroorzaakt waarschijnlijk vertraging."
    elif data["ram_percent"] >= 60:
        ram_status = f"RAM-gebruik is MATIG ({data['ram_percent']}%, {data['ram_used']}GB/{data['ram_total']}GB)."
    else:
        ram_status = f"RAM-gebruik is NORMAAL ({data['ram_percent']}%, {data['ram_used']}GB/{data['ram_total']}GB)."

    diagnoses = []
    stappen = []
    gevonden_ids = set()

    for log in data["logs"]:
        match = re.search(r"EventID:\s*(\d+)", log)
        eventid = match.group(1) if match else None

        if not eventid or eventid in gevonden_ids:
            continue
        gevonden_ids.add(eventid)

        info = EVENTID_KENNISBANK.get(eventid)
        if info:
            diagnoses.append(f"- EventID {eventid}: {info['diagnose']}")
            stappen.append(f"- (EventID {eventid}) {info['stappenplan']}")
        else:
            uitleg = zoek_duckduckgo_uitleg(f"Windows Event ID {eventid}")
            if uitleg:
                diagnoses.append(f"- EventID {eventid}: {uitleg}")
            else:
                diagnoses.append(f"- EventID {eventid}: geen specifieke uitleg gevonden voor deze code.")
            stappen.append(
                f"- (EventID {eventid}) Zoek op 'Windows Event ID {eventid}' in de Gebeurtenissenlogboeken "
                f"(typ 'Logboeken' in het Startmenu) voor meer details, of raadpleeg de Microsoft-documentatie."
            )

    if not diagnoses:
        diagnoses.append("- Geen kritieke Windows-foutcodes gevonden in de recente logs.")

    if data["cpu_load"] >= 80:
        stappen.append("- Open Taakbeheer (Ctrl+Shift+Esc) -> tabblad Processen -> sorteer op CPU, en sluit onnodige programma's af.")
    if data["ram_percent"] >= 85:
        stappen.append("- Open Taakbeheer (Ctrl+Shift+Esc) -> tabblad Processen -> sorteer op Geheugen, en sluit onnodige programma's af. Overweeg extra RAM als dit vaak voorkomt.")
    if not stappen:
        stappen.append("- Geen directe actie nodig; het systeem draait op dit moment stabiel.")

    return (
        "[FALLBACK-ANALYSE, Ollama niet beschikbaar]\n\n"
        "**Systeem Status**\n"
        f"{cpu_status}\n{ram_status}\n\n"
        "**Diagnose**\n"
        f"{chr(10).join(diagnoses)}\n\n"
        "**Stappenplan**\n"
        f"{chr(10).join(stappen)}"
    )

class OllamaInstallDialog(ctk.CTkToplevel):
    """Vraagt de gebruiker toestemming voordat er iets gedownload/geïnstalleerd wordt."""
    def __init__(self, master, on_choice):
        super().__init__(master)
        self.title("Ollama niet gevonden")
        self.geometry("480x260")
        self.configure(fg_color="#050a14")
        self.on_choice = on_choice
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        msg = ctk.CTkLabel(
            self,
            text=(
                "Voor de AI-analyse is Ollama nodig (gratis, lokaal,\n"
                "geen account, geen kosten).\n\n"
                "Ollama is niet gevonden op dit systeem.\n"
                "Wat wil je doen?"
            ),
            font=("Inter", 13), text_color="#e2e8f0", justify="left"
        )
        msg.pack(padx=20, pady=(20, 15))

        ctk.CTkButton(
            self, text="Ja, download en installeer automatisch (geen adminrechten nodig)",
            fg_color="#38bdf8", text_color="#050a14", hover_color="#7dd3fc",
            command=lambda: self._kies("installeer")
        ).pack(fill="x", padx=20, pady=5)

        ctk.CTkButton(
            self, text="Open zelf de downloadpagina",
            fg_color="#64748b", hover_color="#94a3b8",
            command=lambda: self._kies("browser")
        ).pack(fill="x", padx=20, pady=5)

        ctk.CTkButton(
            self, text="Annuleren",
            fg_color="#f43f5e", hover_color="#fb7185",
            command=lambda: self._kies("annuleer")
        ).pack(fill="x", padx=20, pady=5)

    def _kies(self, keuze):
        self.destroy()
        self.on_choice(keuze)


class EnterpriseDiagnosticsApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Star Trek Enterprise / Cyberpunk Slate Thema
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("SIERRA DIAGNOSTICS // ADVANCED HARDWARE CORE")

        # Venstergrootte dynamisch bepalen op basis van het scherm van de
        # gebruiker, zodat knoppen nooit buiten beeld vallen (bijv. bij een
        # kleiner laptopscherm of andere Windows-schaalinstelling).
        scherm_breedte = self.winfo_screenwidth()
        scherm_hoogte = self.winfo_screenheight()
        venster_breedte = min(1100, scherm_breedte - 100)
        venster_hoogte = min(850, scherm_hoogte - 100)
        x_pos = max(0, (scherm_breedte - venster_breedte) // 2)
        y_pos = max(0, (scherm_hoogte - venster_hoogte) // 2)
        self.geometry(f"{venster_breedte}x{venster_hoogte}+{x_pos}+{y_pos}")
        self.minsize(650, 450)
        self.resizable(True, True)
        self.configure(fg_color="#050a14")

        # Vervolgactie na een geslaagde Ollama-installatie (standaard: de
        # hoofdanalyse starten). Wordt tijdelijk overschreven als de
        # installatie via het vraag-veld werd getriggerd.
        self._na_installatie_actie = None

        # --- HEADER (altijd bovenaan zichtbaar, buiten de scrollbare inhoud) ---
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.pack(fill="x", padx=20, pady=15, side="top")

        self.title_label = ctk.CTkLabel(self.header_frame, text="SIERRA-DIAGNOSTICS // WINDOWS SYSTEM CORE", 
                                         font=("Orbitron", 18, "bold"), text_color="#38bdf8")
        self.title_label.pack(side="left")

        self.sub_label = ctk.CTkLabel(self.header_frame, text="ENGINE: LOKALE AI (OLLAMA - GRATIS)", 
                                       font=("Orbitron", 11), text_color="#64748b")
        self.sub_label.pack(side="right")

        # --- ANALYSE-KNOP (altijd onderaan gereserveerd en zichtbaar,
        # ongeacht hoeveel inhoud er tussenin staat) ---
        self.btn_analyze = ctk.CTkButton(self, text="START QUANTUM DIAGNOSTISCHE ANALYSE", font=("Orbitron", 13, "bold"),
                                          fg_color="#38bdf8", text_color="#050a14", hover_color="#7dd3fc", height=45,
                                          command=self.start_ai_analysis)
        self.btn_analyze.pack(fill="x", padx=30, pady=15, side="bottom")

        # --- SCROLLBARE INHOUD (alles ertussen; schuift indien nodig) ---
        self.scroll_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll_frame.pack(fill="both", expand=True, side="top")

        # --- SECTIE 1: STATISCHE SPECIFICATIES (Bovenbalk) ---
        self.spec_frame = ctk.CTkFrame(self.scroll_frame, fg_color="#0f172a", border_width=1, border_color="#1e293b")
        self.spec_frame.pack(fill="x", padx=30, pady=5)
        
        cpu_brand = platform.processor() or "Generic Windows CPU"
        spec_text = f"OS ARCHITECTURE: {platform.system()} {platform.machine()}  |  CPU MODEL: {cpu_brand}"
        self.spec_label = ctk.CTkLabel(self.spec_frame, text=spec_text, font=("Orbitron", 10, "bold"), text_color="#ffcc66")
        self.spec_label.pack(pady=8)

        # --- METRICS GRID (Live data) ---
        self.grid_frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        self.grid_frame.pack(fill="x", padx=20, pady=5)
        self.grid_frame.columnconfigure((0, 1), weight=1)

        # CPU CARD
        self.cpu_card = ctk.CTkFrame(self.grid_frame, fg_color="#0f172a", border_width=1, border_color="#1e293b")
        self.cpu_card.grid(row=0, column=0, padx=10, pady=5, sticky="nsew")
        self.cpu_title = ctk.CTkLabel(self.cpu_card, text="⚙️ CPU STATUS", font=("Orbitron", 12), text_color="#38bdf8")
        self.cpu_title.pack(pady=5)
        self.cpu_metric = ctk.CTkLabel(self.cpu_card, text="--%", font=("Orbitron", 28, "bold"), text_color="#ffffff")
        self.cpu_metric.pack(pady=10)

        # RAM CARD
        self.ram_card = ctk.CTkFrame(self.grid_frame, fg_color="#0f172a", border_width=1, border_color="#1e293b")
        self.ram_card.grid(row=0, column=1, padx=10, pady=5, sticky="nsew")
        self.ram_title = ctk.CTkLabel(self.ram_card, text="🧠 SYSTEM RAM RETRIEVAL", font=("Orbitron", 12), text_color="#38bdf8")
        self.ram_title.pack(pady=5)
        self.ram_metric = ctk.CTkLabel(self.ram_card, text="--%", font=("Orbitron", 28, "bold"), text_color="#ffffff")
        self.ram_metric.pack(pady=5)
        self.ram_details = ctk.CTkLabel(self.ram_card, text="-- GB / -- GB VERBRUIKT", font=("Inter", 11), text_color="#64748b")
        self.ram_details.pack(pady=2)

        # --- WINDOWS EVENT LOGS CARD ---
        self.logs_card = ctk.CTkFrame(self.scroll_frame, fg_color="#0f172a", border_width=1, border_color="#1e293b")
        self.logs_card.pack(fill="both", expand=True, padx=30, pady=5)
        self.logs_title = ctk.CTkLabel(self.logs_card, text="⚠️ ACTIVE WINDOWS EVENT LOGS (CRITICAL & ERROR)", font=("Orbitron", 12), text_color="#f43f5e")
        self.logs_title.pack(pady=5, anchor="w", padx=15)
        self.logs_textbox = ctk.CTkTextbox(self.logs_card, fg_color="#090d16", font=("Consolas", 11), text_color="#cbd5e1", height=120)
        self.logs_textbox.pack(fill="both", expand=True, padx=15, pady=5)

        # --- AI ADVICE CARD ---
        self.ai_card = ctk.CTkFrame(self.scroll_frame, fg_color="#0f172a", border_width=1, border_color="#ffcc66")
        self.ai_card.pack(fill="both", expand=True, padx=30, pady=10)
        self.ai_title = ctk.CTkLabel(self.ai_card, text="🤖 STARFLEET OMNI-DIAGNOSTIC REPORT (OLLAMA)", font=("Orbitron", 12), text_color="#ffcc66")
        self.ai_title.pack(pady=5, anchor="w", padx=15)
        self.ai_textbox = ctk.CTkTextbox(self.ai_card, fg_color="#090d16", font=("Inter", 12), text_color="#e2e8f0", wrap="word", height=160)
        self.ai_textbox.pack(fill="both", expand=True, padx=15, pady=5)
        self.ai_textbox.insert("0.0", "Klik op de knop hieronder om de Windows Event Logs te analyseren via de lokale, gratis AI (Ollama)...")

        # --- VRAAG-SECTIE (nieuw): vrije vragen stellen over logs/foutmeldingen ---
        self.vraag_card = ctk.CTkFrame(self.scroll_frame, fg_color="#0f172a", border_width=1, border_color="#1e293b")
        self.vraag_card.pack(fill="both", expand=True, padx=30, pady=(5, 15))
        self.vraag_title = ctk.CTkLabel(self.vraag_card, text="💬 STEL EEN VRAAG OVER DE LOGS OF FOUTMELDINGEN", 
                                         font=("Orbitron", 12), text_color="#38bdf8")
        self.vraag_title.pack(pady=5, anchor="w", padx=15)

        self.vraag_input_frame = ctk.CTkFrame(self.vraag_card, fg_color="transparent")
        self.vraag_input_frame.pack(fill="x", padx=15, pady=(0, 5))

        self.vraag_entry = ctk.CTkEntry(self.vraag_input_frame, 
                                         placeholder_text="Bijv. 'Wat betekent EventID 41 precies?' of 'Is dit gevaarlijk?'",
                                         font=("Inter", 12), height=36)
        self.vraag_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.vraag_entry.bind("<Return>", lambda event: self.stel_vraag())

        self.btn_vraag = ctk.CTkButton(self.vraag_input_frame, text="Vraag stellen", width=130, height=36,
                                        fg_color="#38bdf8", text_color="#050a14", hover_color="#7dd3fc",
                                        command=self.stel_vraag)
        self.btn_vraag.pack(side="right")

        self.vraag_antwoord_textbox = ctk.CTkTextbox(self.vraag_card, fg_color="#090d16", font=("Inter", 12), 
                                                       text_color="#e2e8f0", wrap="word", height=140)
        self.vraag_antwoord_textbox.pack(fill="both", expand=True, padx=15, pady=(0, 10))
        self.vraag_antwoord_textbox.insert("0.0", "Stel hier een vrije vraag over de gevonden foutmeldingen of over Windows-problemen in het algemeen. Het antwoord verschijnt hier.")

        self.update_metrics()

    def get_silent_telemetry(self):
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory()
        
        telemetry = {
            "cpu_load": cpu,
            "ram_percent": ram.percent,
            "ram_used": round(ram.used / (1024**3), 2),
            "ram_total": round(ram.total / (1024**3), 2),
            "logs": []
        }

        if platform.system() == "Windows":
            try:
                hand = win32evtlog.OpenEventLog(None, "System")
                flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
                events = win32evtlog.ReadEventLog(hand, flags, 0)
                count = 0
                for event in events:
                    if event.EventType in (1, 2) and count < 5: 
                        telemetry["logs"].append(f"[{event.TimeCreated}] Source: {event.SourceName} (EventID: {event.EventID})")
                        count += 1
            except Exception as e:
                telemetry["logs"].append(f"Fout bij geruisloos lezen Event Log: {str(e)}")

        return telemetry

    def update_metrics(self):
        data = self.get_silent_telemetry()
        self.cpu_metric.configure(text=f"{data['cpu_load']}%")
        self.ram_metric.configure(text=f"{data['ram_percent']}%")
        self.ram_details.configure(text=f"{data['ram_used']} GB / {data['ram_total']} GB VERBRUIKT")
        
        self.logs_textbox.delete("0.0", "end")
        if not data["logs"]:
            self.logs_textbox.insert("0.0", "GEEN ACUTE WINDOWS SYSTEM ERRORS IN DE RECENTE LOGS.")
        else:
            self.logs_textbox.insert("0.0", "\n".join(data["logs"]))

        self.after(2000, self.update_metrics)

    def start_ai_analysis(self):
        if is_ollama_bereikbaar():
            self._start_analyse_thread()
            return

        if is_ollama_geinstalleerd():
            self.ai_textbox.delete("0.0", "end")
            self.ai_textbox.insert(
                "0.0",
                "Ollama is geïnstalleerd maar reageert nog niet. Wacht een paar "
                "seconden (Ollama start soms na opstarten pas op) en probeer opnieuw."
            )
            return

        # Ollama is helemaal niet gevonden: vraag toestemming aan de gebruiker
        self._na_installatie_actie = self._start_analyse_thread
        OllamaInstallDialog(self, self._verwerk_installatie_keuze)

    def _verwerk_installatie_keuze(self, keuze):
        doel_textbox = self.ai_textbox if self._na_installatie_actie == self._start_analyse_thread else self.vraag_antwoord_textbox
        if keuze == "installeer":
            if platform.system() != "Windows":
                webbrowser.open(OLLAMA_DOWNLOAD_PAGE)
                doel_textbox.delete("0.0", "end")
                doel_textbox.insert(
                    "0.0",
                    "Automatische installatie wordt alleen ondersteund op Windows. "
                    "De downloadpagina is geopend in je browser."
                )
                return
            doel_textbox.delete("0.0", "end")
            doel_textbox.insert("0.0", "OLLAMA WORDT GEDOWNLOAD EN GEÏNSTALLEERD... Dit kan 1-2 minuten duren.")
            threading.Thread(target=self._download_en_installeer_ollama, daemon=True).start()
        elif keuze == "browser":
            webbrowser.open(OLLAMA_DOWNLOAD_PAGE)
            doel_textbox.delete("0.0", "end")
            doel_textbox.insert(
                "0.0",
                "De Ollama-downloadpagina is geopend in je browser. Installeer "
                "Ollama en probeer daarna opnieuw."
            )
        # bij "annuleer" doen we niets

    def _download_en_installeer_ollama(self):
        doel_textbox = self.ai_textbox if self._na_installatie_actie == self._start_analyse_thread else self.vraag_antwoord_textbox
        try:
            installer_pad = os.path.join(tempfile.gettempdir(), "OllamaSetup.exe")

            self.after(0, lambda: self._update_status("Installatiebestand wordt gedownload...", doel_textbox))
            with requests.get(OLLAMA_INSTALLER_URL, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(installer_pad, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)

            self.after(0, lambda: self._update_status("Installatie wordt uitgevoerd (geen adminrechten nodig)...", doel_textbox))
            # /SILENT is de officiële vlag van de Ollama-installer (InnoSetup),
            # installeert zonder vensters te tonen in het gebruikersprofiel.
            subprocess.run([installer_pad, "/SILENT"], check=True, timeout=300)

            self.after(0, lambda: self._update_status("Wachten tot Ollama opstart...", doel_textbox))
            gelukt = False
            for _ in range(30):
                time.sleep(2)
                if is_ollama_bereikbaar():
                    gelukt = True
                    break

            if not gelukt:
                self.after(0, lambda: self._update_status(
                    "Installatie voltooid, maar Ollama reageert nog niet.\n"
                    "Open eventueel een nieuwe terminal, of herstart dit programma "
                    "en probeer het opnieuw.", doel_textbox
                ))
                return

            self.after(0, lambda: self._update_status(f"Taalmodel '{OLLAMA_MODEL}' wordt gedownload (eenmalig, ± 2 GB)...", doel_textbox))
            ollama_pad = shutil.which("ollama") or OLLAMA_EXE_PAD
            subprocess.run([ollama_pad, "pull", OLLAMA_MODEL], check=True, timeout=1800)

            self.after(0, lambda: self._update_status("Installatie voltooid! Bezig met verwerken...", doel_textbox))
            vervolg = self._na_installatie_actie or self._start_analyse_thread
            self.after(500, vervolg)

        except Exception as e:
            fout = str(e)
            self.after(0, lambda: self._update_status(
                f"Automatische installatie is mislukt:\n{fout}\n\n"
                f"Installeer Ollama handmatig via {OLLAMA_DOWNLOAD_PAGE} en probeer daarna opnieuw.", doel_textbox
            ))

    def _update_status(self, tekst, textbox=None):
        doel = textbox if textbox is not None else self.ai_textbox
        doel.delete("0.0", "end")
        doel.insert("0.0", tekst)

    def _start_analyse_thread(self):
        self.ai_textbox.delete("0.0", "end")
        self.ai_textbox.insert("0.0", "LOKALE AI WORDT GERAADPLEEGD (OLLAMA)... RECENTE WINDOWS ERRORS WORDEN GEANALYSEERD...")
        threading.Thread(target=self.run_online_ai, daemon=True).start()

    def run_online_ai(self):
        data = self.get_silent_telemetry()

        prompt = f"""
        Je bent de hoofdcomputer van de USS Enterprise (Starfleet AI). Analyseer deze Windows-diagnostiek:
        - CPU LOAD: {data['cpu_load']}%
        - RAM: {data['ram_percent']}% verbruikt ({data['ram_used']}GB/{data['ram_total']}GB)
        - Recente fouten uit Windows Event Log: {data['logs']}.

        Geef een PROFESSIONEEL EN TECHNISCH STAPPENPLAN in het Nederlands om dit Windows-systeem stabieler en sneller te maken.

        Gebruik exact de opbouw:
        - **Systeem Status**: Beoordeling van de huidige belasting.
        - **Diagnose**: Wat betekenen de specifieke Windows EventID logboekfouten?
        - **Stappenplan**: Welke concrete Windows-menu's of instellingen moet de gebruiker openen om dit op te lossen? (Bijv. "Ga naar Instellingen -> Systeem -> ...").

        Antwoord zakelijk, overzichtelijk, direct en in het Nederlands.
        """

        try:
            headers = {"Content-Type": "application/json"}
            payload = {
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False
            }
            response = requests.post(OLLAMA_CHAT_URL, headers=headers, json=payload, timeout=120)

            if response.status_code == 200:
                result_json = response.json()
                advice = result_json.get("message", {}).get("content", "").strip()
                if not advice:
                    advice = bouw_lokaal_rapport(data)
            else:
                advice = bouw_lokaal_rapport(data)

        except Exception:
            # Ollama gaf om welke reden dan ook geen bruikbaar antwoord:
            # val terug op de gratis, sleutelloze lokale analyse.
            advice = bouw_lokaal_rapport(data)

        self.after(0, lambda: self.show_advice(advice))


    def show_advice(self, advice):
        self.ai_textbox.delete("0.0", "end")
        self.ai_textbox.insert("0.0", advice)

    # --- VRIJE VRAGEN OVER LOGS/FOUTMELDINGEN ---

    def stel_vraag(self):
        vraag = self.vraag_entry.get().strip()
        if not vraag:
            return

        if is_ollama_bereikbaar():
            self._start_vraag_thread(vraag)
            return

        if is_ollama_geinstalleerd():
            self._update_status(
                "Ollama is geïnstalleerd maar reageert nog niet. Wacht een paar "
                "seconden en probeer opnieuw.", self.vraag_antwoord_textbox
            )
            return

        # Ollama niet gevonden: vraag toestemming, en onthoud dat we na
        # installatie deze specifieke vraag alsnog willen beantwoorden.
        self._na_installatie_actie = lambda: self._start_vraag_thread(vraag)
        OllamaInstallDialog(self, self._verwerk_installatie_keuze)

    def _start_vraag_thread(self, vraag):
        self._update_status("BEZIG MET NADENKEN OVER JE VRAAG...", self.vraag_antwoord_textbox)
        threading.Thread(target=self._beantwoord_vraag, args=(vraag,), daemon=True).start()

    def _beantwoord_vraag(self, vraag):
        data = self.get_silent_telemetry()
        context_logs = "\n".join(data["logs"]) if data["logs"] else "Geen recente foutmeldingen gevonden."

        prompt = f"""
        Je bent een Windows-diagnose-assistent. Dit zijn de recente Windows Event
        Log meldingen op de pc van de gebruiker:
        {context_logs}

        Huidige CPU-belasting: {data['cpu_load']}%. Huidig RAM-gebruik: {data['ram_percent']}%.

        De gebruiker heeft de volgende vraag over deze informatie (of over
        Windows-problemen in het algemeen):
        "{vraag}"

        Geef een duidelijk, behulpzaam en concreet antwoord in het Nederlands.
        Verwijs waar relevant naar specifieke Windows-menu's of instellingen.
        """

        try:
            payload = {
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False
            }
            response = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=120)
            if response.status_code == 200:
                result_json = response.json()
                antwoord = result_json.get("message", {}).get("content", "").strip()
                if not antwoord:
                    antwoord = self._fallback_vraag_antwoord(vraag)
            else:
                antwoord = self._fallback_vraag_antwoord(vraag)
        except Exception:
            antwoord = self._fallback_vraag_antwoord(vraag)

        self.after(0, lambda: self._update_status(antwoord, self.vraag_antwoord_textbox))

    def _fallback_vraag_antwoord(self, vraag):
        """Gratis, sleutelloze fallback als Ollama geen antwoord geeft: probeer
        een kort, algemeen antwoord via DuckDuckGo."""
        uitleg = zoek_duckduckgo_uitleg(vraag)
        if uitleg:
            return f"[Fallback via DuckDuckGo, Ollama niet beschikbaar]\n\n{uitleg}"
        return (
            "Kon geen antwoord genereren: Ollama gaf geen bruikbaar resultaat en "
            "de gratis zoekfunctie vond ook niets specifieks voor deze vraag. "
            "Probeer de vraag anders te formuleren, of controleer of Ollama actief is."
        )

if __name__ == "__main__":
    app = EnterpriseDiagnosticsApp()
    app.mainloop()
