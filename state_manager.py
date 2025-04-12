# state_manager.py (Struttura Modulare a Fasi)
# Questo modulo agisce da router: riceve l'input, determina la fase
# e delega l'elaborazione al modulo logico specifico per quella fase.

import streamlit as st
from utils import log_message
from config import INITIAL_STATE # Importa stato iniziale per fallback

# Importa i moduli logici specifici per ogni fase
# Metti un try-except per gestire casi in cui i file potrebbero mancare
# o per permettere un'implementazione graduale.
try:
    from phases import assessment_logic
except ImportError:
    log_message("WARN: Modulo 'assessment_logic.py' non trovato in 'phases/'.")
    assessment_logic = None
try:
    from phases import restructuring_logic
except ImportError:
    log_message("WARN: Modulo 'restructuring_logic.py' non trovato in 'phases/'.")
    restructuring_logic = None
try:
    from phases import erp_logic
except ImportError:
    log_message("WARN: Modulo 'erp_logic.py' non trovato in 'phases/'.")
    erp_logic = None
try:
    from phases import act_logic
except ImportError:
    log_message("WARN: Modulo 'act_logic.py' non trovato in 'phases/'.")
    act_logic = None
try:
    from phases import disgust_logic
except ImportError:
    log_message("WARN: Modulo 'disgust_logic.py' non trovato in 'phases/'.")
    disgust_logic = None
try:
    from phases import relapse_logic
except ImportError:
    log_message("WARN: Modulo 'relapse_logic.py' non trovato in 'phases/'.")
    relapse_logic = None
# Aggiungi import per altri moduli di fase qui...


def process_user_message(user_msg, current_state):
    """
    Funzione principale per processare il messaggio utente.
    Determina la fase corrente e delega al modulo logico appropriato.

    Args:
        user_msg (str): Il messaggio dell'utente.
        current_state (dict): Lo stato attuale della conversazione.

    Returns:
        tuple: (str, dict) -> (risposta_del_bot, nuovo_stato)
    """
    if not isinstance(current_state, dict):
        log_message(f"ERRORE CRITICO in state_manager: current_state non è un dizionario! Ricevuto: {type(current_state)}. Ripristino.")
        current_state = INITIAL_STATE.copy() # Fallback a stato iniziale
        bot_response = "Si è verificato un errore interno nello stato della conversazione. Riavvio la sessione."
        return bot_response, current_state

    current_phase = current_state.get('phase', 'START') # Ottieni la fase corrente
    log_message(f"State Manager: Ricevuto messaggio per fase '{current_phase}'")

    new_state = current_state.copy() # Lavora su una copia per evitare side effects
    bot_response = "Mi dispiace, non so come gestire questa fase." # Fallback

    handler_module = None
    handler_function_name = 'handle' # Nome convenzione per la funzione handler in ogni modulo fase

    # --- Routing basato sulla Fase ---
    # Mappa le fasi ai moduli logici importati
    if current_phase.startswith('ASSESSMENT_') or current_phase == 'START':
        handler_module = assessment_logic
    elif current_phase.startswith('RESTRUCTURING_'):
        handler_module = restructuring_logic
    elif current_phase.startswith('ERP_'):
        handler_module = erp_logic
    elif current_phase.startswith('ACT_'):
         handler_module = act_logic
    elif current_phase.startswith('DISGUST_'):
         handler_module = disgust_logic
    elif current_phase.startswith('RELAPSE_'):
         handler_module = relapse_logic
    # Aggiungi altri elif per nuove fasi qui...
    else:
        log_message(f"WARN: Fase '{current_phase}' non riconosciuta dallo state_manager.")
        # Potrebbe gestire un fallback generico qui o lasciare la risposta di default

    # --- Delega al Modulo Specifico ---
    if handler_module and hasattr(handler_module, handler_function_name):
        try:
            log_message(f"State Manager: Delega alla funzione '{handler_function_name}' del modulo {handler_module.__name__}")
            # Chiama la funzione handle del modulo specifico
            handler_func = getattr(handler_module, handler_function_name)
            bot_response, new_state = handler_func(user_msg, new_state)
            log_message(f"State Manager: Ricevuto nuovo stato con fase '{new_state.get('phase')}' da {handler_module.__name__}")

        except Exception as e:
            log_message(f"ERRORE durante l'esecuzione di {handler_module.__name__}.{handler_function_name}: {type(e).__name__}: {e}\nTraceback: {traceback.format_exc()}")
            bot_response = "Mi dispiace, si è verificato un errore interno durante l'elaborazione della tua richiesta in questa fase."
            # Mantiene lo stato precedente in caso di errore nel modulo delegato
            new_state = current_state
    elif handler_module:
        log_message(f"ERRORE: Modulo '{handler_module.__name__}' trovato ma manca la funzione handler '{handler_function_name}'.")
        bot_response = f"Errore di configurazione: la logica per la fase '{current_phase}' non è implementata correttamente."
        new_state = current_state # Mantiene stato precedente
    else:
        log_message(f"WARN: Nessun modulo handler trovato per la fase '{current_phase}'. Uso risposta fallback.")
        # Qui potremmo opzionalmente chiamare un LLM generico come fallback estremo
        # ma per ora usiamo la risposta di default definita sopra.
        new_state = current_state # Mantiene stato precedente

    # Assicura che lo stato restituito sia un dizionario
    if not isinstance(new_state, dict):
        log_message(f"ERRORE CRITICO in state_manager: new_state restituito da handler non è un dict! Tipo: {type(new_state)}. Ripristino.")
        new_state = current_state # Ripristina stato precedente
        bot_response = "Errore interno nello stato restituito dalla logica della fase."

    return bot_response, new_state

