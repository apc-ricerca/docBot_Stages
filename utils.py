# utils.py (Struttura Modulare a Fasi)
# Questo file rimane invariato rispetto alla versione precedente (ibrida).
# Contiene funzioni di utilità come il logging.

import datetime
import streamlit as st

def log_message(message):
    """Funzione semplice per stampare messaggi di log con timestamp sulla console."""
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"LOG [{now}]: {message}", flush=True)
    except Exception as e:
        print(f"LOGGING ERROR: {e} - Original message: {message}")

# Aggiungi qui altre funzioni di utilità se necessario
