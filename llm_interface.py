# llm_interface.py (Struttura Modulare a Fasi)
# Questo file rimane invariato rispetto alla versione precedente (ibrida).
# Gestisce l'interazione con l'API Gemini.

import streamlit as st
import google.generativeai as genai
import traceback
from utils import log_message

def generate_response(prompt, history=None, model=None):
    """
    Genera una risposta usando il modello Gemini specificato o quello in session_state.
    Gestisce la history nel formato atteso da Gemini.

    Args:
        prompt (str): Il prompt completo per il turno corrente.
        history (list, optional): Lista di dizionari nel formato Gemini. Defaults to None.
        model (genai.GenerativeModel, optional): Istanza del modello da usare.
                                                 Se None, usa st.session_state.model_gemini.
                                                 Defaults to None.

    Returns:
        str: La risposta testuale generata dal modello, o un messaggio di errore.
    """
    model_gemini_local = model if model is not None else st.session_state.get('model_gemini')

    if not model_gemini_local:
         log_message("ERRORE CRITICO: Modello Gemini non fornito né trovato in session_state.")
         return "Mi dispiace, si è verificato un errore interno nel contattare il modello AI."

    try:
        cleaned_history = None
        if history and isinstance(history, list):
             cleaned_history = [
                 msg for msg in history
                 if isinstance(msg, dict) and \
                    msg.get("role") in ["user", "model"] and \
                    isinstance(msg.get("parts"), list) and \
                    msg["parts"] and \
                    isinstance(msg["parts"][0], str) and \
                    msg["parts"][0].strip() not in ["...", "Sto pensando...", ""]
             ]

        if cleaned_history:
             log_message(f"Avvio chat Gemini con {len(cleaned_history)} elementi nella history.")
             chat_session = model_gemini_local.start_chat(history=cleaned_history)
             response = chat_session.send_message(prompt, request_options={'timeout': 120})
             log_message("Prompt inviato tramite chat_session.send_message().")
        else:
             log_message("Invio prompt a Gemini senza history precedente (generate_content).")
             response = model_gemini_local.generate_content(prompt, request_options={'timeout': 120})
             log_message("Prompt inviato tramite model.generate_content().")

        log_message("Risposta API ricevuta da Gemini.")

        # --- Gestione Risposta e Filtri Sicurezza ---
        try:
             if not response.candidates:
                 block_reason = "N/D"; safety_ratings = "N/D"
                 if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                      block_reason = response.prompt_feedback.block_reason
                      safety_ratings = response.prompt_feedback.safety_ratings
                      log_message(f"WARN: Risposta vuota (bloccata?). Motivo Blocco Prompt: {block_reason}, Ratings: {safety_ratings}")
                 else:
                      log_message("WARN: Risposta vuota (response.candidates è vuoto/None) senza prompt_feedback.")
                 st.warning("La risposta potrebbe essere stata bloccata dai filtri di sicurezza o è vuota.")
                 return "Non ho potuto generare una risposta completa, potrebbe essere stata bloccata per motivi di sicurezza. Prova a riformulare."

             candidate = response.candidates[0]

             if candidate.finish_reason != "STOP":
                 log_message(f"WARN: Generazione Gemini terminata per motivo non ottimale: {candidate.finish_reason}.")

             if candidate.finish_reason == "SAFETY":
                  safety_ratings_candidate = candidate.safety_ratings
                  log_message(f"WARN: Risposta bloccata per motivi di sicurezza (Candidate). Ratings: {safety_ratings_candidate}")
                  st.warning("La risposta è stata bloccata dai filtri di sicurezza.")
                  return "La mia risposta è stata bloccata per motivi di sicurezza. Per favore, riformula la tua richiesta."

             if candidate.content and candidate.content.parts:
                 bot_response_text = "".join(part.text for part in candidate.content.parts if hasattr(part, 'text'))
             else:
                 log_message("WARN: Risposta Gemini ricevuta ma senza parti testuali nel candidato.")
                 bot_response_text = ""

             if not bot_response_text.strip():
                  log_message("WARN: Testo della risposta estratto è vuoto o solo spazi bianchi.")
                  return "Ho ricevuto una risposta vuota dal modello. Potrebbe esserci un problema o un blocco implicito."

             log_message(f"Testo risposta estratto: '{bot_response_text[:80]}...'")
             return bot_response_text

        except (ValueError, IndexError, AttributeError) as resp_err:
             log_message(f"ERRORE nell'accedere al contenuto della risposta Gemini: {resp_err}")
             st.warning("La struttura della risposta del modello non è come previsto.")
             return "Mi dispiace, non ho potuto elaborare correttamente la risposta dal modello AI."

    except Exception as e:
        error_type = type(e).__name__
        log_message(f"ERRORE Imprevisto durante Generazione Risposta Gemini: {error_type}: {e}\nTraceback: {traceback.format_exc()}")
        st.error(f"Errore durante la comunicazione con il modello AI: {e}")
        return "Mi dispiace, si è verificato un errore tecnico imprevisto. Riprova più tardi."

