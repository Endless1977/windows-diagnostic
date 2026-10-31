# Windows Diagnostic

Desktop-programma (Python / customtkinter) dat CPU, RAM en de Windows Event Logs
uitleest, fouten analyseert en een stappenplan in het Nederlands genereert.

## Functies
- Live CPU- en RAM-meter
- Laatste fouten uit het Windows System Event Log
- AI-analyse via **Ollama** (gratis, lokaal, geen API-sleutel). Is Ollama niet
  aanwezig, dan biedt het programma aan om het automatisch te installeren.
- Fallback zonder AI: ingebouwde kennisbank met veelvoorkomende EventID's + DuckDuckGo
- Vraagveld om extra vragen te stellen over foutmeldingen
- Venster past zich aan het scherm aan; inhoud is scrollbaar

## Starten
```
pip install -r requirements.txt
python Diagnose.py
```

## Naar .exe
```
pip install pyinstaller
pyinstaller --onefile --windowed --collect-all customtkinter Diagnose.py
```
