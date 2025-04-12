# app.py (Struttura Modulare a Fasi)
# Gestisce l'UI Streamlit e chiama il gestore dello stato/logica.

import streamlit as st
import os
import google.generativeai as genai
import traceback
# Import necessari per moduli importati (anche se non usati direttamente qui)
import faiss
import pickle
import numpy
import pandas
import glob
import re
import time

# Importa funzioni e configurazioni dagli altri moduli
from utils import log_message
from config import (
    EMBEDDING_MODEL_NAME, GENERATION_MODEL_NAME, SAFETY_SETTINGS_GEMINI,
    GENERATION_CONFIG_GEMINI, INTRO_MESSAGE, INITIAL_STATE
)
# Importa la funzione di caricamento RAG (eseguita all'avvio)
from rag_utils import load_rag_indexes
# Importa il GESTORE della logica principale (che poi delegherà alle fasi)
from state_manager import process_user_message

# --- CONFIGURAZIONE INIZIALE E CARICAMENTO RISORSE ---
# (Identica alle versioni precedenti, eseguita una sola volta)
if 'initialized' not in st.session_state:
    st.session_state.initialized = False

if not st.session_state.initialized:
    log_message("--- INIZIO INIZIALIZZAZIONE APPLICAZIONE (Modulare a Fasi) ---")
    init_success = True
    rag_load_success = False

    # --- 1. Configurazione API Key ---
    log_message("1. Configurazione API Key...")
    GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY") # Usa Streamlit secrets
    if not GOOGLE_API_KEY:
        st.error("!!! ERRORE CRITICO: Secret 'GOOGLE_API_KEY' non trovato!"); log_message("ERRORE: GOOGLE_API_KEY non trovato.")
        init_success = False; st.stop()
    if init_success:
        try:
            genai.configure(api_key=GOOGLE_API_KEY)
            log_message("   API Key Google configurata.")
        except Exception as e:
            st.error(f"!!! ERRORE Configurazione API Key: {e}"); log_message(f"ERRORE Config API Key: {e}"); init_success = False; st.stop()

    # --- 2. Salvataggio Nome Modello Embedding ---
    if init_success:
        log_message("2. Configurazione Modello Embedding...")
        st.session_state.embedding_model_name = EMBEDDING_MODEL_NAME
        log_message(f"   Modello Embedding impostato: {st.session_state.embedding_model_name}")

    # --- 3. Configurazione Modello Generativo ---
    if init_success:
        log_message("3. Configurazione Modello Generativo...")
        log_message(f"   Modello Generativo Selezionato: {GENERATION_MODEL_NAME}")
        try:
            model_gemini = genai.GenerativeModel(
                model_name=GENERATION_MODEL_NAME,
                generation_config=GENERATION_CONFIG_GEMINI,
                safety_settings=SAFETY_SETTINGS_GEMINI
            )
            st.session_state.model_gemini = model_gemini # Salva istanza in session_state
            log_message(f"   Modello Generativo '{GENERATION_MODEL_NAME}' configurato.")
        except Exception as e:
            st.error(f"!!! ERRORE Configurazione Modello Generativo ({GENERATION_MODEL_NAME}): {e}"); log_message(f"ERRORE Config Modello Generativo: {e}"); init_success = False; st.stop()

    # --- 4. Salvataggio Costanti e Stato Iniziale ---
    if init_success:
        log_message("4. Salvataggio Costanti e Stato Iniziale...")
        st.session_state.INITIAL_STATE = INITIAL_STATE.copy()
        st.session_state.INTRO_MESSAGE = INTRO_MESSAGE
        log_message("   Costanti e Stato Iniziale salvati.")

    # --- 5. Caricamento Indici e Mappe RAG ---
    if init_success:
        rag_load_success = load_rag_indexes() # Chiama funzione da rag_utils
        if not rag_load_success:
             log_message("ERRORE nel caricamento RAG rilevato in app.py.")
             st.warning("Caricamento RAG fallito o parziale. La ricerca contesto potrebbe essere limitata.")
             # Non blocchiamo l'app, ma RAG potrebbe non funzionare
    else:
        rag_load_success = False # Assicura che sia False se l'init precedente è fallito

    # --- Fine Blocco Inizializzazione ---
    st.session_state.initialized = init_success
    st.session_state.rag_enabled = rag_load_success

    log_message(f"--- INIZIALIZZAZIONE COMPLETATA (Successo App: {st.session_state.initialized}, RAG Caricato: {st.session_state.rag_enabled}) ---")
    if not st.session_state.initialized:
         st.error("Applicazione non inizializzata correttamente a causa di errori critici.")
         st.stop()

# --- GESTIONE SESSION STATE (Chat History e Stato Conversazione) ---
# Inizializza chat history se non esiste
if 'messages' not in st.session_state:
    intro = st.session_state.get('INTRO_MESSAGE', "Ciao! Come posso aiutarti?")
    st.session_state.messages = [{"role": "assistant", "content": intro}]
    log_message("Chat history inizializzata.")

# Inizializza lo stato della conversazione se non esiste
if 'state' not in st.session_state:
    initial = st.session_state.get('INITIAL_STATE')
    if initial and isinstance(initial, dict):
        st.session_state.state = initial.copy()
        # Assicura che lo schema sia un dizionario
        if 'schema' not in st.session_state.state or not isinstance(st.session_state.state.get('schema'), dict):
             st.session_state.state['schema'] = initial.get('schema', {}).copy()
        log_message(f"Stato conversazione inizializzato: {st.session_state.state}")
    else:
        log_message("ERRORE CRITICO: Stato iniziale (INITIAL_STATE) non trovato o non valido!")
        st.error("Errore critico nell'inizializzazione dello stato!")
        st.session_state.state = {'phase': 'ERROR', 'schema': {}} # Stato di fallback
        # st.stop() # Potrebbe essere troppo drastico

# --- INTERFACCIA STREAMLIT ---
# st.title("Assistente Cognitivo-Comportamentale (Struttura a Fasi)")

# Mostra la chat history esistente
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Input utente
if prompt := st.chat_input("Scrivi qui il tuo messaggio..."):
    # Aggiungi messaggio utente alla history e visualizzalo
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Genera risposta del bot chiamando il state_manager
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        message_placeholder.markdown("...") # Indicatore "Sto pensando..."

        # Verifica stato prima di chiamare la logica
        if 'state' in st.session_state and isinstance(st.session_state.state, dict):
            current_state_for_logic = st.session_state.state
            try:
                # --- Chiamata al gestore della logica principale ---
                response, new_state = process_user_message(prompt, current_state_for_logic)
                # --------------------------------------------------

                # Aggiorna stato e visualizza/salva risposta
                st.session_state.state = new_state # Aggiorna lo stato globale
                log_message(f"Stato aggiornato da state_manager - Fase: {st.session_state.state.get('phase')}")
                message_placeholder.markdown(response) # Mostra la risposta completa
                st.session_state.messages.append({"role": "assistant", "content": response})

            except Exception as e:
                log_message(f"ERRORE durante process_user_message: {type(e).__name__}: {e}\nTraceback: {traceback.format_exc()}")
                st.error(f"Si è verificato un errore nell'elaborazione della risposta: {e}")
                error_message = "Mi dispiace, si è verificato un errore interno. Per favore, prova a riformulare o riavvia la chat."
                message_placeholder.markdown(error_message)
                st.session_state.messages.append({"role": "assistant", "content": error_message})
        else:
            st.error("Errore critico: Stato conversazione perso o non valido.")
            log_message("ERRORE CRITICO: st.session_state.state non trovato o non valido prima di process_user_message.")
            error_message = "Errore interno grave (stato perso). Si consiglia di riavviare la chat."
            message_placeholder.markdown(error_message)
            st.session_state.messages.append({"role": "assistant", "content": error_message})


# --- Sidebar ---
st.sidebar.title("Opzioni")

# Pulsante per pulire la chat
if st.sidebar.button("Pulisci Chat e Riavvia"):
    log_message("Pulsante 'Pulisci Chat e Riavvia' premuto.")
    intro = st.session_state.get('INTRO_MESSAGE', "Ciao!")
    initial = st.session_state.get('INITIAL_STATE')

    if intro and initial and isinstance(initial, dict):
        st.session_state.messages = [{"role": "assistant", "content": intro}]
        st.session_state.state = initial.copy()
        st.session_state.state['schema'] = initial.get('schema', {}).copy()
        log_message("Chat e stato resettati ai valori iniziali.")
        st.rerun()
    else:
         log_message("ERRORE nel Reset: Stato iniziale o messaggio intro non validi.")
         st.error("Impossibile resettare la chat correttamente.")

# Mostra lo stato corrente nella sidebar per debug
st.sidebar.divider()
st.sidebar.subheader("Stato Conversazione (Debug)")
if 'state' in st.session_state and isinstance(st.session_state.state, dict):
    st.sidebar.markdown(f"**Fase Corrente:** `{st.session_state.state.get('phase', 'N/D')}`")
    st.sidebar.caption("Schema Raccolto:")
    st.sidebar.json(st.session_state.state.get('schema', {}))
    # with st.sidebar.expander("Mostra stato completo"):
    #     st.sidebar.json(st.session_state.state)
else:
    st.sidebar.warning("Stato non ancora inizializzato o non valido.")

st.sidebar.divider()
st.sidebar.caption(f"RAG Abilitato: {'Sì' if st.session_state.get('rag_enabled', False) else 'No'}")
st.sidebar.caption(f"Modello Generativo: {GENERATION_MODEL_NAME}")

