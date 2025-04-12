# phases/assessment_logic.py (Struttura Modulare a Fasi)
# Contiene la logica specifica per le fasi di Assessment (START, GET_EXAMPLE, ..., CONFIRM_SCHEMA, EDIT_*).
# Aggiornato: 12 Aprile 2025

import streamlit as st # Necessario per accedere a st.session_state.model_gemini
import time
import traceback

# Importa funzioni e costanti necessarie
from utils import log_message
from llm_interface import generate_response
from rag_utils import search_global_rag, search_step_rag # Potrebbe servire nel fallback
from config import CONFERME, NEGAZIONI_O_DUBBI, PHASE_TO_CHAPTER_KEY_MAP, INITIAL_STATE

# --- Funzione Helper per creare il testo del riepilogo ---
# (Spostata qui perché specifica per l'assessment)
def _create_summary_text(schema):
    """Genera il testo formattato per il riepilogo dello schema."""
    ec = schema.get('ec', 'N/D')
    pv1 = schema.get('pv1', 'N/D')
    ts1 = schema.get('ts1', 'N/D')
    sv2 = schema.get('sv2')
    ts2 = schema.get('ts2')
    sv2_display = sv2 if sv2 else "Nessuna valutazione secondaria significativa identificata"
    ts2_display = ts2 if ts2 else "Nessuna strategia di evitamento ciclo identificata"

    summary = f"""Perfetto, grazie. Ricapitolando questo ciclo:

* **Evento Critico (EC):** {ec}
* **Ossessione (PV1):** {pv1}
* **Compulsione (TS1):** {ts1}
* **Seconda Valutazione (SV2):** {sv2_display}
* **Tentativo Soluzione 2 (TS2 - Evitamento Ciclo):** {ts2_display}

Questa sequenza ti sembra descrivere bene l'esperienza? (Puoi dire 'sì' o indicare cosa modificare)"""
    return summary

# --- Funzione Handler Principale per le Fasi di Assessment ---
def handle(user_msg, current_state):
    """
    Gestisce la logica per tutte le fasi relative all'Assessment.

    Args:
        user_msg (str): Il messaggio dell'utente.
        current_state (dict): Lo stato attuale della conversazione.

    Returns:
        tuple: (str, dict) -> (risposta_del_bot, nuovo_stato)
    """
    new_state = current_state.copy()
    current_phase = new_state.get('phase', 'START')
    log_message(f"Assessment Logic: Gestione fase '{current_phase}'")

    bot_response_text = "" # Risposta predefinita
    llm_task_prompt = None # Prompt specifico per LLM

    # Costanti locali
    conferme = CONFERME
    negazioni_o_dubbi = NEGAZIONI_O_DUBBI

    # --- Logica Specifica per Sotto-Fasi dell'Assessment ---

    # Fase 0: START
    if current_phase == 'START':
        new_state['phase'] = 'ASSESSMENT_INTRO'
        bot_response_text = "Ottimo, iniziamo! Per capire meglio come aiutarti, vorrei guidarti nella costruzione del tuo 'Schema di Funzionamento' personale. Analizzeremo insieme una situazione specifica per vedere come si attiva il ciclo del DOC. Sei d'accordo se ti chiedo di raccontarmi un esempio?"
        log_message("Assessment Logic: Transizione START -> ASSESSMENT_INTRO.")

    # Fase 1: ASSESSMENT_INTRO
    elif current_phase == 'ASSESSMENT_INTRO':
        user_msg_processed = user_msg.strip().lower()
        is_confirmation = user_msg_processed in conferme or \
                          any(user_msg_processed.startswith(conf + " ") for conf in conferme if isinstance(conf, str)) or \
                          any(word in conferme for word in user_msg_processed.split())

        if is_confirmation:
             new_state['phase'] = 'ASSESSMENT_GET_EXAMPLE'
             llm_task_prompt = "L'utente ha accettato di fornire un esempio. Guida empaticamente l'utente a descrivere una situazione concreta e recente in cui ha provato ansia/disagio/pensieri ossessivi. Spiega brevemente che questo è l'**Evento Critico (EC)** e chiedigli di raccontarlo."
             log_message("Assessment Logic: Transizione ASSESSMENT_INTRO -> ASSESSMENT_GET_EXAMPLE.")
        else:
             new_state['phase'] = 'ASSESSMENT_GET_EXAMPLE'
             log_message("Assessment Logic: Input non conferma diretta, assumo sia EC -> ASSESSMENT_GET_EXAMPLE.")
             # Processa l'input come potenziale EC nella prossima fase

    # Fase 2: ASSESSMENT_GET_EXAMPLE
    elif current_phase == 'ASSESSMENT_GET_EXAMPLE':
        new_state['schema']['ec'] = user_msg # Salva input come EC
        new_state['phase'] = 'ASSESSMENT_GET_PV1'
        ec_text = new_state['schema'].get('ec', 'la situazione descritta')
        llm_task_prompt = f"Grazie per aver descritto l'Evento Critico: '{ec_text[:100]}...'. Ora vorrei capire l'**Ossessione (PV1)**. Con tono empatico, chiedi specificamente quale è stato il primo pensiero, immagine, dubbio o paura (l'ossessione) che ha avuto in *quel momento*."
        log_message("Assessment Logic: EC salvato. Transizione a ASSESSMENT_GET_PV1.")

    # Fase 3: ASSESSMENT_GET_PV1
    elif current_phase == 'ASSESSMENT_GET_PV1':
        new_state['schema']['pv1'] = user_msg # Salva input come PV1
        new_state['phase'] = 'ASSESSMENT_GET_TS1'
        pv1_text = new_state['schema'].get('pv1', 'il pensiero/paura precedente')
        llm_task_prompt = f"Ok, l'Ossessione (PV1) identificata è '{pv1_text[:100]}...'. Adesso passiamo alla **Compulsione (TS1)**. Formula una domanda naturale per chiedere cosa ha fatto, pensato o sentito *in risposta diretta* a quell'ossessione per cercare di gestirla (es: azione fisica, pensiero specifico, rituale mentale, ricerca rassicurazione, evitamento, anche se avvenuta dopo ma collegata)."
        log_message("Assessment Logic: PV1 salvato. Transizione a ASSESSMENT_GET_TS1.")

    # Fase 4: ASSESSMENT_GET_TS1 (con validazione LLM)
    elif current_phase == 'ASSESSMENT_GET_TS1':
        pv1_text_for_validation = new_state['schema'].get('pv1', 'N/D')
        ec_text_for_validation = new_state['schema'].get('ec', 'N/D')
        validation_prompt = f"""ANALISI RISPOSTA UTENTE PER COMPULSIONE (TS1)
Contesto: Ossessione (PV1) "{pv1_text_for_validation}" dopo Evento Critico (EC) "{ec_text_for_validation}". Domanda Posta: Chiedeva la Compulsione (TS1) - reazione immediata O DIFFERITA. Risposta Utente: "{user_msg}"
TASK: La risposta descrive una Compulsione (TS1) valida (reazione fisica/mentale/rituale/rassicurazione/evitamento, anche differita o pensiero di rassicurazione legato a azione differita)?
- Se SÌ: Estrai la descrizione PIÙ SIGNIFICATIVA (es. "Lavaggio mani differito", "Rassicurazione mentale + Controllo successivo").
- Se NO (es. SOLO emozioni, 'non ho fatto nulla' senza implicare azione/pensiero, 'non saprei', divaga), rispondi ESATTAMENTE con la parola 'NONE'.
Output Atteso: Descrizione concisa TS1 o NONE."""

        log_message("Assessment Logic: Avvio validazione TS1...")
        time.sleep(1) # Pausa opzionale
        # Accede al modello LLM tramite st.session_state
        extracted_ts1 = generate_response(prompt=validation_prompt, history=[], model=st.session_state.get('model_gemini'))
        log_message(f"Assessment Logic: Risultato validazione TS1: '{extracted_ts1}'")

        if extracted_ts1 and extracted_ts1.strip().upper() != 'NONE' and len(extracted_ts1.strip()) > 0:
            ts1_text_extracted = extracted_ts1.strip()
            new_state['schema']['ts1'] = ts1_text_extracted
            new_state['phase'] = 'ASSESSMENT_GET_SV2'
            pv1_text_context = new_state['schema'].get('pv1', 'l\'ossessione')
            llm_task_prompt = f"Bene, la Compulsione (TS1) è stata '{ts1_text_extracted[:100]}...'. Ora, concentriamoci sul momento **subito dopo** l'Ossessione ('{pv1_text_context[:100]}...'). Chiedi gentilmente cosa ha **PENSATO** o **GIUDICATO** riguardo all'Ossessione o alla Compulsione stessa. Sottolinea che cerchiamo la **valutazione cognitiva/metacognitiva (Seconda Valutazione - SV2)**, non solo l'emozione."
            log_message("Assessment Logic: TS1 valido. Transizione a ASSESSMENT_GET_SV2.")
        else:
            new_state['phase'] = 'ASSESSMENT_GET_TS1' # Rimani qui
            pv1_text = new_state['schema'].get('pv1', 'l\'ossessione')
            llm_task_prompt = f"Ok, grazie per la risposta ('{user_msg[:100]}...'). A volte la compulsione non è un'azione immediata. Ripensando a dopo aver avuto l'ossessione '{pv1_text[:100]}...', c'è stato *qualsiasi* comportamento (anche successivo) o pensiero specifico (ripetersi frasi, controllare mentalmente) che hai messo in atto *proprio per rispondere* a quell'ossessione? Prova a descrivermi questa reazione."
            log_message("Assessment Logic: TS1 non valido. Richiedo.")

    # Fase 5: ASSESSMENT_GET_SV2 (con validazione LLM)
    elif current_phase == 'ASSESSMENT_GET_SV2':
        ts1_text_for_validation = new_state['schema'].get('ts1', 'N/D')
        sv2_validation_prompt = f"""ANALISI RISPOSTA UTENTE PER SECONDA VALUTAZIONE (SV2)
Contesto: Dopo Ossessione (PV1) e Compulsione (TS1) "{ts1_text_for_validation}". Domanda Posta: Chiedeva pensiero/giudizio dopo ossessione (non solo emozione). Risposta Utente: "{user_msg}"
TASK: La risposta descrive una **Valutazione Cognitiva Secondaria (SV2)** (pensiero, giudizio, valutazione metacognitiva)? NON solo un'emozione.
- Se SÌ (es. 'ho pensato fosse terribile', 'mi sono sentito stupido', 'ho capito che non bastava'), estrai SOLO la descrizione essenziale del PENSIERO/GIUDIZIO.
- Se NO (es. SOLO 'ansia', 'paura'; 'non lo so'; ripete TS1; divaga), rispondi ESATTAMENTE con la parola 'NONE'.
Output Atteso: Descrizione SV2 o NONE."""

        log_message("Assessment Logic: Avvio validazione SV2...")
        time.sleep(1)
        extracted_sv2 = generate_response(prompt=sv2_validation_prompt, history=[], model=st.session_state.get('model_gemini'))
        log_message(f"Assessment Logic: Risultato validazione SV2: '{extracted_sv2}'")

        if extracted_sv2 and extracted_sv2.strip().upper() != 'NONE' and len(extracted_sv2.strip()) > 0:
            sv2_text_extracted = extracted_sv2.strip()
            new_state['schema']['sv2'] = sv2_text_extracted
            new_state['phase'] = 'ASSESSMENT_GET_TS2'
            llm_task_prompt = f"Ok, abbiamo raccolto diversi elementi. Ora l'ultimo punto per questo esempio: il **Tentativo di Soluzione 2 (TS2)**. Chiedi gentilmente se, pensando a tutta l'esperienza, l'utente ha poi messo in atto strategie per **evitare in futuro situazioni simili**, o per **prevenire l'ossessione**, o per **gestire diversamente la compulsione**. Focalizzati solo su strategie future per evitare/modificare il ciclo."
            log_message("Assessment Logic: SV2 valida. Transizione a ASSESSMENT_GET_TS2.")
        else:
             new_state['schema']['sv2'] = None
             new_state['schema']['ts2'] = None # Salta TS2 se SV2 non è significativa
             new_state['phase'] = 'ASSESSMENT_CONFIRM_SCHEMA'
             bot_response_text = _create_summary_text(new_state['schema'])
             log_message("Assessment Logic: SV2 non valida. Salto TS2. Transizione a ASSESSMENT_CONFIRM_SCHEMA.")

    # Fase 6: ASSESSMENT_GET_TS2 (con validazione LLM)
    elif current_phase == 'ASSESSMENT_GET_TS2':
        sv2_text_for_validation = new_state['schema'].get('sv2', 'N/D')
        ts2_validation_prompt = f"""ANALISI RISPOSTA UTENTE PER TENTATIVO SOLUZIONE 2 (TS2 - Evitamento Ciclo)
Contesto: Dopo ciclo EC->PV1->TS1->SV2 (SV2="{sv2_text_for_validation}"). Domanda Posta: Chiedeva strategie future per EVITARE/MODIFICARE il ciclo. Risposta Utente: "{user_msg}"
TASK: La risposta descrive una strategia/intenzione/tentativo (TS2) per evitare/prevenire il ciclo futuro (evitare EC, prevenire PV1, gestire diversamente TS1)? Considera validi anche tentativi falliti o lotta interna.
- Se SÌ (es. 'ho smesso di X', 'evito Y', 'mi costringo a non Z', 'proverò a K', 'cerco di resistere'), estrai la descrizione essenziale.
- Se NO (es. 'no', 'niente', 'non saprei', 'non ci ho pensato', divaga), rispondi ESATTAMENTE con la parola 'NONE'.
Output Atteso: Descrizione TS2 o NONE."""

        log_message("Assessment Logic: Avvio validazione TS2...")
        time.sleep(1)
        extracted_ts2 = generate_response(prompt=ts2_validation_prompt, history=[], model=st.session_state.get('model_gemini'))
        log_message(f"Assessment Logic: Risultato validazione TS2: '{extracted_ts2}'")

        # Logica fallback (identica a prima)
        ts2_valido = False; testo_ts2_finale = None
        if extracted_ts2:
            extracted_ts2_pulito = extracted_ts2.strip()
            if extracted_ts2_pulito.upper() != 'NONE' and len(extracted_ts2_pulito) > 0:
                testo_ts2_finale = extracted_ts2_pulito; ts2_valido = True
                log_message("Assessment Logic: TS2 valido estratto.")
            else: log_message("Assessment Logic: LLM ha indicato TS2 non valido ('NONE' o vuoto).")
        else:
            log_message("Assessment Logic: WARN Validazione TS2 vuota (blocco/errore?). Applico fallback.")
            negazioni_ts2 = ['no', 'niente', 'non saprei', 'non ci ho pensato', 'nessuno', 'nessuna']
            user_msg_minuscolo = user_msg.strip().lower()
            if not any(neg in user_msg_minuscolo for neg in negazioni_ts2) and len(user_msg_minuscolo) > 5:
                log_message("Assessment Logic: Fallback: Uso input utente grezzo come TS2.")
                testo_ts2_finale = user_msg.strip(); ts2_valido = True
            else: log_message("Assessment Logic: Fallback: Input utente negazione/corto. TS2 non valido.")

        # Assegna e transiziona
        new_state['schema']['ts2'] = testo_ts2_finale if ts2_valido else None
        new_state['phase'] = 'ASSESSMENT_CONFIRM_SCHEMA'
        bot_response_text = _create_summary_text(new_state['schema'])
        log_message("Assessment Logic: Gestito TS2. Transizione a ASSESSMENT_CONFIRM_SCHEMA.")

    # Fase 7: ASSESSMENT_CONFIRM_SCHEMA
    elif current_phase == 'ASSESSMENT_CONFIRM_SCHEMA':
        user_msg_processed = user_msg.strip().lower()
        is_confirmation = any(word in conferme for word in user_msg_processed.split()) or user_msg_processed in conferme
        is_modification_request = any(word in negazioni_o_dubbi for word in user_msg_processed.split()) or \
                                  any(keyword in user_msg_processed for keyword in ["modifi", "cambia", "aggiust", "corregg", "rivedere", "precisare", "sbagliato", "errato"])

        if is_confirmation and not is_modification_request:
            # --- Passaggio a Fase Successiva (Placeholder) ---
            new_state['phase'] = 'ASSESSMENT_COMPLETE' # Indica fine assessment
            bot_response_text = "Ottimo, grazie per la conferma! Abbiamo completato questa prima fase di valutazione dell'esempio."
            # TODO: Aggiungere prompt per transizione a fase successiva (es. Ristrutturazione)
            log_message("Assessment Logic: Schema confermato. Transizione a ASSESSMENT_COMPLETE.")
        elif is_modification_request:
            new_state['phase'] = 'ASSESSMENT_AWAIT_EDIT_TARGET'
            bot_response_text = "Certamente. Quale parte specifica dello schema vuoi modificare o precisare? (es. 'Evento Critico', 'Ossessione', 'Compulsione', 'Seconda Valutazione', 'Tentativo Soluzione 2')."
            log_message("Assessment Logic: Richiesta modifica. Transizione a ASSESSMENT_AWAIT_EDIT_TARGET.")
        else:
            log_message("Assessment Logic: Risposta non chiara a conferma schema. Richiedo.")
            summary_part = _create_summary_text(new_state['schema']).split("Perfetto, grazie. ")[1]
            bot_response_text = f"Scusa, non ho afferrato. Lo schema riassunto è:\n\n{summary_part}\n\nVa bene così? Dimmi 'sì' o indica cosa vorresti cambiare."
            new_state['phase'] = 'ASSESSMENT_CONFIRM_SCHEMA' # Rimani qui

    # Fase 7.1: ASSESSMENT_AWAIT_EDIT_TARGET
    elif current_phase == 'ASSESSMENT_AWAIT_EDIT_TARGET':
         user_input_lower = user_msg.lower()
         target_key = None
         # Logica identificazione target (identica a prima)
         if 'seconda valutazione' in user_input_lower or 'sv2' in user_input_lower: target_key = 'sv2'
         elif 'tentativo' in user_input_lower or 'ts2' in user_input_lower or 'soluzione 2' in user_input_lower or 'evitamento ciclo' in user_input_lower : target_key = 'ts2'
         elif 'compulsione' in user_input_lower or 'ts1' in user_input_lower: target_key = 'ts1'
         elif 'ossessione' in user_input_lower or 'pv1' in user_input_lower or 'prima valutazione' in user_input_lower : target_key = 'pv1'
         elif 'evento' in user_input_lower or 'critico' in user_input_lower or 'ec' in user_input_lower or 'situazione' in user_input_lower: target_key = 'ec'

         if target_key:
             new_state['editing_target'] = target_key # Salva cosa modificare
             new_state['phase'] = f'ASSESSMENT_EDIT_{target_key.upper()}'
             target_names = {'ec': 'Evento Critico', 'pv1': 'Ossessione', 'ts1': 'Compulsione', 'sv2': 'Seconda Valutazione', 'ts2': 'Tentativo Soluzione 2'}
             target_name = target_names.get(target_key, target_key)
             llm_task_prompt = f"Ok, hai indicato di voler modificare '{target_name}'. Per favore, fornisci la nuova descrizione completa per questo punto."
             log_message(f"Assessment Logic: Target modifica '{target_key}'. Transizione a {new_state['phase']}.")
         else:
             bot_response_text = "Non ho capito bene quale punto vuoi modificare. Puoi ripeterlo usando termini come 'Evento Critico', 'Ossessione', 'Compulsione', 'Seconda Valutazione' o 'Tentativo Soluzione 2'?"
             new_state['phase'] = 'ASSESSMENT_AWAIT_EDIT_TARGET' # Rimani qui
             log_message("Assessment Logic: Target modifica non identificato. Richiedo.")

    # Fase 7.2: ASSESSMENT_EDIT_X
    elif current_phase.startswith('ASSESSMENT_EDIT_'):
        target_key = current_state.get('editing_target')
        if target_key and target_key in new_state.get('schema', {}):
             log_message(f"Assessment Logic: Ricevuto nuovo valore per {target_key}: {user_msg[:50]}...")
             new_state['schema'][target_key] = user_msg # Aggiorna schema
             new_state['phase'] = 'ASSESSMENT_CONFIRM_SCHEMA' # Torna a conferma
             bot_response_text = _create_summary_text(new_state['schema']) # Mostra schema aggiornato
             log_message(f"Assessment Logic: Valore '{target_key}' aggiornato. Ritorno a ASSESSMENT_CONFIRM_SCHEMA.")
        else:
             log_message(f"Assessment Logic: ERRORE CRITICO in EDIT - editing_target '{target_key}' non valido/trovato. Ripristino.")
             new_state = current_state # Ripristina
             if 'editing_target' in new_state: del new_state['editing_target']
             new_state['phase'] = 'ASSESSMENT_CONFIRM_SCHEMA'
             bot_response_text = "Scusa, problema interno nella modifica. Rivediamo lo schema attuale:\n\n" + _create_summary_text(new_state['schema']).split("Perfetto, grazie. ")[1]

    # Fase Finale Assessment (Placeholder)
    elif current_phase == 'ASSESSMENT_COMPLETE':
        log_message("Assessment Logic: Fase ASSESSMENT_COMPLETE. Gestione fallback/transizione.")
        # Qui si potrebbe chiedere se passare alla fase successiva o gestire input generici.
        # Lasciamo che il fallback generico gestisca per ora.
        llm_task_prompt = None # Attiva fallback generico

    # --- Gestione Chiamata LLM Specifica (se llm_task_prompt è impostato) ---
    if llm_task_prompt:
        log_message(f"Assessment Logic: Eseguo LLM per task specifico: {llm_task_prompt}")
        # Costruisci prompt e history come nella versione precedente
        system_prompt = f"""Sei un assistente empatico per il supporto al DOC (TCC).
FASE CONVERSAZIONE: {new_state['phase']}. SCHEMA UTENTE: {new_state.get('schema', {})}.
ISTRUZIONI: Rispondi in ITALIANO. Tono empatico, chiaro, CONCISO. Fai UNA domanda alla volta. Non usare sigle. Non chiedere info già in SCHEMA.
OBIETTIVO SPECIFICO: {llm_task_prompt}"""

        chat_history_for_llm = []
        history_source = st.session_state.get('messages', [])
        if len(history_source) > 1:
            for msg in history_source[:-1]:
                 role = 'model' if msg.get('role') == 'assistant' else msg.get('role')
                 content = msg.get('content', '')
                 if role in ['user', 'model'] and content:
                     chat_history_for_llm.append({'role': role, 'parts': [content]})

        bot_response_text = generate_response(
            prompt=f"{system_prompt}\n\n---\n\nUltimo Messaggio Utente: {user_msg}",
            history=chat_history_for_llm,
            model=st.session_state.get('model_gemini')
        )

    # --- Fallback Generico Interno al Modulo (se nessuna logica ha prodotto risposta) ---
    elif not bot_response_text:
        log_message(f"Assessment Logic: Nessuna logica specifica o task LLM per fase '{current_phase}'. Eseguo fallback generico...")

        # Recupera chiave RAG per la fase corrente
        current_step_key = PHASE_TO_CHAPTER_KEY_MAP.get(current_phase)
        rag_context = ""; search_type = "Nessuna"
        query_for_rag = user_msg

        # Prova RAG Step
        if current_step_key and st.session_state.get('rag_enabled', False) and current_step_key in st.session_state.get('step_indexes', {}):
            try:
                rag_results = search_step_rag(query_for_rag, current_step_key, top_k=2)
                if rag_results: search_type = f"Step ({current_step_key})"
            except Exception as e: log_message(f"ERRORE search_step_rag in fallback: {e}")
        # Prova RAG Globale se Step fallisce o non applicabile
        if not rag_context and st.session_state.get('rag_enabled', False) and 'global_index' in st.session_state and st.session_state.global_index is not None:
             try:
                 rag_results_global = search_global_rag(query_for_rag, top_k=3)
                 if rag_results_global: rag_results = rag_results_global; search_type = "Globale"
             except Exception as e: log_message(f"ERRORE search_global_rag in fallback: {e}")

        # Formatta contesto RAG
        if rag_results:
              rag_context = "\n\n---\nCONTESTO DAL MATERIALE DI SUPPORTO (Potrebbe essere utile, ma non citarlo direttamente):\n"
              for i, result in enumerate(rag_results): rag_context += f"[{i+1}] {result.get('content', '')}\n\n"
              log_message(f"Assessment Logic: Fallback RAG ({search_type}) trovato.")
        else: log_message(f"Assessment Logic: Fallback RAG ({search_type}) non trovato.")

        # Prompt LLM Generico per il fallback
        system_prompt_generic = f"""Sei un assistente empatico per il supporto al DOC (TCC).
FASE CONVERSAZIONE ATTUALE: {new_state['phase']}. SCHEMA UTENTE: {new_state.get('schema', {})}.{rag_context}
ISTRUZIONI: Rispondi in ITALIANO. Tono empatico, chiaro, CONCISO. L'utente ha inviato un messaggio che non rientra nel flusso previsto per la fase attuale o la fase è generica (es. ASSESSMENT_COMPLETE). Cerca di rispondere in modo utile e pertinente al messaggio, usando il contesto RAG se rilevante. Se appropriato, guida gentilmente verso il prossimo passo logico (es. se in ASSESSMENT_COMPLETE, chiedi se vuole procedere). Fai UNA domanda alla volta se necessario."""

        chat_history_for_llm = [] # Ricostruisci history
        history_source = st.session_state.get('messages', [])
        if len(history_source) > 1:
            for msg in history_source[:-1]:
                 role = 'model' if msg.get('role') == 'assistant' else msg.get('role')
                 content = msg.get('content', '')
                 if role in ['user', 'model'] and content:
                     chat_history_for_llm.append({'role': role, 'parts': [content]})

        bot_response_text = generate_response(
            prompt=f"{system_prompt_generic}\n\n---\n\nUltimo Messaggio Utente: {user_msg}",
            history=chat_history_for_llm,
            model=st.session_state.get('model_gemini')
        )
        log_message("Assessment Logic: Eseguito LLM generico di fallback.")

    # Fallback finale se ancora nessuna risposta
    if not bot_response_text:
        log_message("Assessment Logic: WARN - bot_response_text ancora vuoto. Risposta fallback finale.")
        bot_response_text = "Non sono sicuro di come rispondere. Potresti riformulare?"

    # Pulisci 'editing_target' se non siamo più in una fase di modifica
    if 'editing_target' in new_state and not new_state.get('phase','').startswith('ASSESSMENT_EDIT_'):
         del new_state['editing_target']

    log_message(f"Assessment Logic: Fine gestione fase '{current_phase}'. Nuovo stato: '{new_state.get('phase')}'")
    return bot_response_text, new_state
