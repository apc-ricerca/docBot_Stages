# phases/act_logic.py (Struttura Modulare a Fasi)
# Placeholder per la logica delle fasi ACT / Mindfulness / Valori.

import streamlit as st
from utils import log_message
# Importa altre dipendenze necessarie

def handle(user_msg, current_state):
    """
    Gestisce la logica per le fasi ACT / Valori / Mindfulness.
    ATTENZIONE: Logica non ancora implementata.
    """
    new_state = current_state.copy()
    current_phase = new_state.get('phase', 'UNKNOWN')
    log_message(f"ACT Logic: Ricevuto messaggio per fase '{current_phase}' - LOGICA NON IMPLEMENTATA.")

    # TODO: Implementare la logica per le fasi:
    # - ACT_VALUES_INTRO / ACT_VALUES_EXPLORE
    # - ACT_DEFUSION_INTRO / ACT_DEFUSION_PRACTICE
    # - MINDFULNESS_INTRO / MINDFULNESS_PRACTICE
    # - etc.

    # Risposta placeholder
    bot_response = f"Siamo nella fase ACT/Mindfulness ('{current_phase}'), ma questa parte non è ancora stata sviluppata nel dettaglio. Cosa vorresti fare?"

    return bot_response, new_state
