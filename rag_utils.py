# rag_utils.py (Struttura Modulare a Fasi)
# Questo file rimane invariato rispetto alla versione precedente (ibrida).
# Gestisce il caricamento e la ricerca negli indici RAG (globale e per step).

import streamlit as st
import faiss
import numpy as np
import pickle
import glob
import os
import re
import time
import google.generativeai as genai
import traceback
from utils import log_message

def load_rag_indexes():
    """Carica tutti gli indici FAISS (step e globale) e le mappe Pickle."""
    log_message("5. Caricamento Indici e Mappe RAG...")
    rag_load_success = True
    st.session_state.global_index = None
    st.session_state.global_map = {}
    st.session_state.step_indexes = {}
    st.session_state.step_maps = {}

    global_index_filename = "global_workbook.index"
    global_map_filename = "global_workbook_map.pkl"

    # Carica Globale
    if os.path.exists(global_index_filename) and os.path.exists(global_map_filename):
        try:
            st.session_state.global_index = faiss.read_index(global_index_filename)
            with open(global_map_filename, 'rb') as f:
                st.session_state.global_map = pickle.load(f)
            if st.session_state.global_index is not None and st.session_state.global_index.ntotal > 0:
                 log_message(f"   Indice Globale ({st.session_state.global_index.ntotal} vettori) e Mappa Globale ({len(st.session_state.global_map)} elem.) caricati.")
            else:
                 log_message(f"WARN: Indice globale '{global_index_filename}' caricato ma vuoto o corrotto.")
        except Exception as e:
            st.error(f"Errore durante il caricamento RAG globale: {e}"); log_message(f"ERRORE RAG globale: {e}"); rag_load_success = False
    else:
        st.warning(f"File RAG globale non trovato ('{global_index_filename}' o '{global_map_filename}'). La ricerca globale non sarà disponibile."); log_message(f"WARN: File RAG globale non trovato.");

    # Carica Step
    step_index_files = glob.glob("step_*.index")
    log_message(f"   Trovati {len(step_index_files)} file indice per gli step.")
    if not step_index_files:
         log_message("ATTENZIONE: Nessun file indice 'step_*.index' trovato! La ricerca RAG per step non sarà disponibile.");

    for index_filepath in step_index_files:
        base_name = os.path.basename(index_filepath)
        step_key = base_name.replace(".index", "")
        map_filename = f"{step_key}_map.pkl"
        log_message(f"   Tentativo caricamento RAG step: '{step_key}'")

        if os.path.exists(index_filepath) and os.path.exists(map_filename):
            try:
                step_index = faiss.read_index(index_filepath)
                if step_index.ntotal == 0:
                    log_message(f"   WARN: Indice step '{step_key}' caricato ma è vuoto.")
                with open(map_filename, 'rb') as f:
                    step_map = pickle.load(f)
                st.session_state.step_indexes[step_key] = step_index
                st.session_state.step_maps[step_key] = step_map
                log_message(f"     - OK: '{step_key}' caricato (Indice: {step_index.ntotal} vettori, Mappa: {len(step_map)} elementi).")
            except Exception as e:
                 st.error(f"Errore caricamento RAG step '{step_key}': {e}"); log_message(f"ERRORE caricamento RAG step '{step_key}': {e}"); rag_load_success = False;
        else:
            st.warning(f"File indice ({index_filepath}) o mappa ({map_filename}) mancanti per step '{step_key}'. Questo step RAG non sarà disponibile."); log_message(f"WARN: File mancanti RAG step '{step_key}'.");

    # Verifica finale
    if not st.session_state.get('global_index') and not st.session_state.get('step_indexes'):
        log_message("ERRORE: Nessun indice RAG (né globale né step) caricato con successo.")
        st.error("Caricamento RAG fallito completamente. La ricerca contesto non funzionerà.")
        rag_load_success = False
    elif rag_load_success:
        log_message("   Caricamento RAG completato (almeno parzialmente).")
    else:
        log_message("ERRORE: Caricamento RAG fallito/incompleto a causa di errori critici.")
        st.warning("Funzionalità RAG potrebbero essere limitate a causa di errori di caricamento.")

    return rag_load_success

# --- Funzioni di Ricerca RAG ---

def search_global_rag(query_text, top_k=3):
    """Cerca nell'indice FAISS globale."""
    log_message(f"Richiesta ricerca RAG Globale (k={top_k}) per: '{query_text[:50]}...'")
    if 'global_index' not in st.session_state or 'global_map' not in st.session_state or \
       'embedding_model_name' not in st.session_state or st.session_state.global_index is None or \
       st.session_state.global_index.ntotal == 0:
        log_message("WARN: Risorse RAG globale non disponibili o indice vuoto per search_global_rag.")
        return []

    index_local = st.session_state.global_index
    id_map_local = st.session_state.global_map
    embedding_model_name_local = st.session_state.embedding_model_name

    try:
        query_embedding_result = genai.embed_content(
            model=embedding_model_name_local,
            content=query_text,
            task_type="RETRIEVAL_QUERY"
        )
        query_embedding = np.array([query_embedding_result['embedding']], dtype='float32')
        distances, indices = index_local.search(query_embedding, top_k)
        results = []
        if indices.size > 0:
             for i, idx in enumerate(indices[0]):
                if idx != -1:
                    chunk_data = id_map_local.get(int(idx))
                    if chunk_data and isinstance(chunk_data, dict):
                        results.append({
                            "id": int(idx),
                            "content": chunk_data.get("content", ""),
                            "metadata": chunk_data.get("metadata", {}),
                            "distance": float(distances[0][i])
                        })
                    else:
                         log_message(f"WARN: Dati non trovati o formato non valido per indice globale {idx} nella mappa.")
        log_message(f"Ricerca RAG Globale ha trovato {len(results)} risultati.")
        return results
    except Exception as e:
        st.error(f"Errore durante la ricerca RAG globale: {e}")
        log_message(f"ERRORE Ricerca RAG Globale: {type(e).__name__}: {e}\nTraceback: {traceback.format_exc()}")
        return []

def search_step_rag(query_text, step_key, top_k=3):
    """Cerca nell'indice FAISS specifico dello step."""
    log_message(f"Richiesta ricerca RAG Step '{step_key}' (k={top_k}) per: '{query_text[:50]}...'")
    if 'step_indexes' not in st.session_state or 'step_maps' not in st.session_state or \
       'embedding_model_name' not in st.session_state or \
       step_key not in st.session_state.step_indexes or step_key not in st.session_state.step_maps or \
       st.session_state.step_indexes[step_key].ntotal == 0:
        log_message(f"WARN: Risorse RAG per step '{step_key}' non disponibili, non trovate o indice vuoto.")
        return []

    index_local = st.session_state.step_indexes[step_key]
    id_map_local = st.session_state.step_maps[step_key]
    embedding_model_name_local = st.session_state.embedding_model_name

    try:
        query_embedding_result = genai.embed_content(
            model=embedding_model_name_local,
            content=query_text,
            task_type="RETRIEVAL_QUERY"
        )
        query_embedding = np.array([query_embedding_result['embedding']], dtype='float32')
        distances, indices = index_local.search(query_embedding, top_k)
        results = []
        if indices.size > 0:
             for i, idx in enumerate(indices[0]):
                if idx != -1:
                    chunk_data = id_map_local.get(int(idx))
                    if chunk_data and isinstance(chunk_data, dict):
                        results.append({
                            "id": int(idx),
                            "content": chunk_data.get("content", ""),
                            "metadata": chunk_data.get("metadata", {}),
                            "distance": float(distances[0][i])
                        })
                    else:
                         log_message(f"WARN: Dati non trovati o formato non valido per indice step {idx} nella mappa '{step_key}'.")
        log_message(f"Ricerca RAG Step '{step_key}' ha trovato {len(results)} risultati.")
        return results
    except Exception as e:
        st.error(f"Errore durante la ricerca RAG step '{step_key}': {e}")
        log_message(f"ERRORE Ricerca RAG Step '{step_key}': {type(e).__name__}: {e}\nTraceback: {traceback.format_exc()}")
        return []
