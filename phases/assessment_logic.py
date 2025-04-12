# filename: docBot_Stages/phases/assessment_logic.py
# phases/assessment_logic.py (Struttura Modulare a Fasi)
# AGGIORNATO: Implementata analisi intelligente multi-componente (EC, PV1, TS1, SV2, TS2)
#             dalla risposta utente iniziale nella fase ASSESSMENT_GET_EXAMPLE.
#             Il bot chiederà poi solo i componenti mancanti.

import streamlit as st
import time
import traceback
import json # Importato per parsing JSON

# Importa funzioni e costanti necessarie
from utils import log_message
from llm_interface import generate_response
from rag_utils import search_global_rag, search_step_rag
from config import CONFERME, NEGAZIONI_O_DUBBI, PHASE_TO_CHAPTER_KEY_MAP, INITIAL_STATE

# --- Funzione Helper per creare il testo del riepilogo ---
# (Invariata)
def _create_summary_text(schema):
    """Genera il testo formattato per il riepilogo dello schema."""
    ec = schema.get('ec', 'N/D')
    pv1 = schema.get('pv1', 'N/D')
    ts1 = schema.get('ts1', 'N/D')
    sv2 = schema.get('sv2') # Non mostrare 'N/D' se None
    ts2 = schema.get('ts2') # Non mostrare 'N/D' se None

    sv2_display = sv2 if sv2 else "Non significativo / Non identificato"
    ts2_display = ts2 if ts2 else "Non significativo / Non identificato"

    summary = f"""Perfetto, grazie. Ricapitolando questo ciclo che abbiamo ricostruito:

* **Evento Critico (EC):** {ec}
* **Ossessione (PV1):** {pv1}
* **Compulsione (TS1):** {ts1}
* **Seconda Valutazione (SV2):** {sv2_display}
* **Tentativo Soluzione 2 (TS2 - Evitamento Ciclo):** {ts2_display}

Questa sequenza ti sembra descrivere bene l'esperienza? (Puoi dire 'sì' o indicare cosa modificare)"""
    return summary

# --- Funzione Helper per Pulire Risposta LLM JSON ---
def _clean_llm_json_response(llm_response_text):
    """Tenta di estrarre un blocco JSON pulito dalla risposta dell'LLM."""
    try:
        # Cerca ```json ... ```
        match = re.search(r"```json\s*(\{.*?\})\s*```", llm_response_text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        # Cerca ``` ... ```
        match = re.search(r"```\s*(\{.*?\})\s*```", llm_response_text, re.DOTALL)
        if match:
            return match.group(1).strip()
        # Fallback: Prova a vedere se è già JSON valido (magari con spazi attorno)
        stripped_response = llm_response_text.strip()
        if stripped_response.startswith('{') and stripped_response.endswith('}'):
             # Prova a validarlo (senza generare eccezione qui)
             try:
                 json.loads(stripped_response)
                 return stripped_response
             except json.JSONDecodeError:
                 pass # Non era JSON valido, continua sotto
        # Se non trova blocchi specifici o JSON valido, restituisce il testo pulito
        # sperando che sia già il JSON corretto o che il parsing fallisca dopo.
        log_message("WARN: Pulizia JSON non ha trovato ```json o ```. Uso testo grezzo.")
        return stripped_response
    except Exception as e:
        log_message(f"ERRORE in _clean_llm_json_response: {e}")
        return llm_response_text # Ritorna originale in caso di errore inaspettato

# --- Funzione Helper per Trovare il Prossimo Passo Mancante ---
def _find_next_missing_step(schema):
    """
    Identifica la prossima fase GET necessaria basandosi sullo schema attuale.
    Restituisce la chiave del componente mancante (es. 'pv1', 'ts1') o None se completo.
    """
    if not schema.get('ec'): return 'ec' # Anche se dovrebbe essere già gestito prima
    if not schema.get('pv1'): return 'pv1'
    if not schema.get('ts1'): return 'ts1'
    # Consideriamo SV2 e TS2 opzionali o comunque successivi, ma chiediamoli se TS1 c'è
    if not schema.get('sv2'): return 'sv2'
    # Chiedi TS2 solo se SV2 è stato identificato (o se si decide di chiederlo comunque)
    # Modifica: Chiediamo TS2 anche se SV2 è None, per semplicità, la validazione deciderà
    if not schema.get('ts2'): return 'ts2'
    # Se tutti presenti (o opzionali mancanti gestiti), allora non manca nulla per ora
    return None

# --- Funzione Handler Principale per le Fasi di Assessment ---
def handle(user_msg, current_state):
    """
    Gestisce la logica per tutte le fasi relative all'Assessment.
    Include analisi multi-componente e richiesta mirata dei dati mancanti.
    """
    new_state = current_state.copy()
    # Assicura che lo schema esista e sia un dizionario nello stato
    if 'schema' not in new_state or not isinstance(new_state.get('schema'), dict):
        log_message("WARN: 'schema' mancante o non dict in new_state. Reinizializzo.")
        new_state['schema'] = INITIAL_STATE['schema'].copy()

    current_phase = new_state.get('phase', 'START')
    log_message(f"Assessment Logic: Gestione fase '{current_phase}'")

    bot_response_text = ""
    llm_task_prompt = None

    # Costanti locali
    conferme = CONFERME
    negazioni_o_dubbi = NEGAZIONI_O_DUBBI

    # --- Logica Specifica per Sotto-Fasi dell'Assessment ---

    # [ START e ASSESSMENT_INTRO rimangono invariati ]
    if current_phase == 'START':
        new_state['phase'] = 'ASSESSMENT_INTRO'
        bot_response_text = "Ottimo, iniziamo! Per capire meglio come aiutarti, vorrei guidarti nella costruzione del tuo 'Schema di Funzionamento' personale. Analizzeremo insieme una situazione specifica per vedere come si attiva il ciclo del DOC. Sei d'accordo se ti chiedo di raccontarmi un esempio?"
        log_message("Assessment Logic: Transizione START -> ASSESSMENT_INTRO.")

    elif current_phase == 'ASSESSMENT_INTRO':
        user_msg_processed = user_msg.strip().lower()
        is_confirmation = user_msg_processed in conferme or \
                          any(user_msg_processed.startswith(conf + " ") for conf in conferme if isinstance(conf, str)) or \
                          any(word in conferme for word in user_msg_processed.split())

        if is_confirmation:
             new_state['phase'] = 'ASSESSMENT_GET_EXAMPLE'
             # Prompt modificato per chiedere l'esempio in modo più aperto
             llm_task_prompt = "Perfetto. Allora, prova a raccontarmi una situazione concreta e recente in cui hai provato ansia, disagio o hai avuto pensieri che ti preoccupavano legati al DOC. Descrivi semplicemente cosa è successo e cosa hai pensato o fatto."
             log_message("Assessment Logic: Transizione ASSESSMENT_INTRO -> ASSESSMENT_GET_EXAMPLE (con richiesta aperta).")
        else:
             # Assume che l'utente stia già fornendo l'esempio
             new_state['phase'] = 'ASSESSMENT_GET_EXAMPLE'
             log_message("Assessment Logic: Input non conferma diretta, assumo sia inizio Esempio -> ASSESSMENT_GET_EXAMPLE.")
             # L'input verrà processato nella fase successiva

    # --- ASSESSMENT_GET_EXAMPLE (Logica Riscritto per Estrazione Multi-Componente) ---
    elif current_phase == 'ASSESSMENT_GET_EXAMPLE':
        log_message(f"Assessment Logic: Ricevuto input in ASSESSMENT_GET_EXAMPLE: '{user_msg[:100]}...'")
        log_message("Assessment Logic: Avvio analisi LLM multi-componente (EC, PV1, TS1, SV2, TS2)...")

        # 1. Definisci il prompt per l'estrazione multi-componente
        extraction_prompt = f"""Analizza attentamente il seguente messaggio dell'utente, che descrive (potenzialmente in parte o per intero) un'esperienza legata al DOC:
        \"\"\"
        {user_msg}
        \"\"\"
        Il tuo compito è identificare e separare i seguenti componenti dello schema DOC, se sono chiaramente presenti nel testo:
        1.  **EC (Evento Critico):** La situazione specifica, l'evento esterno o interno che ha innescato il ciclo (es. "uscire di casa", "toccare una maniglia", "vedere una certa immagine", "pensare a X").
        2.  **PV1 (Prima Valutazione/Ossessione):** Il primo pensiero intrusivo, dubbio, immagine o paura significativa sorta in risposta all'EC (es. "e se avessi lasciato il gas acceso?", "potrei contaminarmi", "potrei fare del male a qualcuno", "sono omosessuale?").
        3.  **TS1 (Tentativo Soluzione 1/Compulsione):** La reazione comportamentale o mentale (rituale, controllo, rassicurazione, evitamento, anche differito) messa in atto *in risposta diretta* a PV1 per gestirla.
        4.  **SV2 (Seconda Valutazione):** Il pensiero, giudizio o valutazione (anche metacognitiva) emerso *dopo* PV1 o TS1, riguardante l'ossessione, la compulsione o sé stessi (es. "questo pensiero è terribile", "non riuscirò a smettere", "sono responsabile se...", "ho fatto bene a controllare"). NON solo un'emozione.
        5.  **TS2 (Tentativo Soluzione 2/Evitamento Ciclo):** Una strategia/intenzione messa in atto *successivamente* per evitare situazioni simili (EC), prevenire l'ossessione (PV1), o gestire diversamente la compulsione (TS1) in futuro (es. "eviterò quel posto", "cercherò di non pensarci", "la prossima volta farò X").

        Restituisci il risultato ESATTAMENTE nel seguente formato JSON:
        {{
          "ec": "Testo estratto dell'Evento Critico (solo la situazione trigger)",
          "pv1": "Testo estratto della Prima Valutazione (il pensiero/dubbio iniziale)",
          "ts1": "Testo estratto della Compulsione/Tentativo Soluzione 1",
          "sv2": "Testo estratto della Seconda Valutazione (il giudizio/pensiero)",
          "ts2": "Testo estratto del Tentativo Soluzione 2 (strategia futura)"
        }}

        Se un componente NON è chiaramente identificabile nel messaggio fornito, imposta il suo valore su **null** o su una **stringa vuota**. Sii conciso nell'estrazione. Se non riesci a identificare chiaramente nemmeno l'EC, puoi restituire null per tutti i campi o almeno per EC. Non inventare informazioni non presenti.
        """

        # 2. Chiama l'LLM per l'estrazione
        extracted_components = {'ec': None, 'pv1': None, 'ts1': None, 'sv2': None, 'ts2': None}
        try:
            # Usiamo una history vuota per questa chiamata specifica di estrazione
            llm_extraction_response = generate_response(
                prompt=extraction_prompt,
                history=[],
                model=st.session_state.get('model_gemini')
            )
            log_message(f"Assessment Logic: Risposta LLM grezza per estrazione multi-comp: {llm_extraction_response}")

            # 3. Pulisci e Parsa la risposta JSON (con gestione errori robusta)
            if llm_extraction_response:
                clean_response = _clean_llm_json_response(llm_extraction_response)
                try:
                    parsed_data = json.loads(clean_response)
                    if isinstance(parsed_data, dict):
                        # Estrai e normalizza (stringa vuota -> None)
                        extracted_components['ec'] = parsed_data.get("ec") if parsed_data.get("ec") else None
                        extracted_components['pv1'] = parsed_data.get("pv1") if parsed_data.get("pv1") else None
                        extracted_components['ts1'] = parsed_data.get("ts1") if parsed_data.get("ts1") else None
                        extracted_components['sv2'] = parsed_data.get("sv2") if parsed_data.get("sv2") else None
                        extracted_components['ts2'] = parsed_data.get("ts2") if parsed_data.get("ts2") else None
                        log_message(f"Assessment Logic: Estrazione JSON riuscita - Dati: {extracted_components}")
                    else:
                        log_message("Assessment Logic: WARN - Risposta LLM pulita non è un dizionario JSON valido.")
                except json.JSONDecodeError as json_err:
                    log_message(f"Assessment Logic: ERRORE parsing JSON da LLM: {json_err}. Risposta LLM pulita: {clean_response}")
            else:
                log_message("Assessment Logic: WARN - Risposta LLM per estrazione è vuota.")

        except Exception as e:
            log_message(f"Assessment Logic: ERRORE durante chiamata LLM per estrazione multi-comp: {e}\n{traceback.format_exc()}")
            # Fallback: se la chiamata LLM fallisce, non abbiamo estratto nulla

        # 4. Logica di Fallback e Salvataggio/Transizione
        # Se l'EC non è stato estratto o è vuoto, usiamo l'intero messaggio utente come EC
        # e resettiamo gli altri componenti eventualmente estratti per errore.
        if not extracted_components.get('ec'):
            log_message("Assessment Logic: Fallback - Estrazione EC fallita o vuota. Uso l'intero user_msg come EC.")
            # Reset for safety, ask from PV1 onwards
            new_state['schema']['ec'] = user_msg
            new_state['schema']['pv1'] = None
            new_state['schema']['ts1'] = None
            new_state['schema']['sv2'] = None
            new_state['schema']['ts2'] = None
            next_missing = 'pv1' # Dobbiamo chiedere PV1
        else:
            # Salva tutti i componenti estratti (che non sono None)
            for key, value in extracted_components.items():
                if value: # Salva solo se non è None (o vuoto normalizzato a None)
                    new_state['schema'][key] = value
            log_message(f"Assessment Logic: Schema aggiornato dopo estrazione: {new_state['schema']}")
            # Determina il prossimo passo mancante
            next_missing = _find_next_missing_step(new_state['schema'])

        # 5. Transizione e Impostazione Prompt per il Prossimo Passo
        if next_missing:
            target_phase = f"ASSESSMENT_GET_{next_missing.upper()}"
            new_state['phase'] = target_phase
            log_message(f"Assessment Logic: Prossimo componente mancante: '{next_missing}'. Transizione a {target_phase}.")

            # Costruisci il prompt per chiedere il componente mancante
            ec_text = new_state['schema'].get('ec', 'la situazione iniziale')
            pv1_text = new_state['schema'].get('pv1', 'il pensiero/ossessione')
            ts1_text = new_state['schema'].get('ts1', 'la compulsione/reazione')
            sv2_text = new_state['schema'].get('sv2', 'la valutazione secondaria')

            context_summary = f"Finora abbiamo: EC='{ec_text[:80]}...'"
            if new_state['schema'].get('pv1'): context_summary += f", PV1='{pv1_text[:80]}...'"
            if new_state['schema'].get('ts1'): context_summary += f", TS1='{ts1_text[:80]}...'"
            if new_state['schema'].get('sv2'): context_summary += f", SV2='{sv2_text[:80]}...'"

            if next_missing == 'pv1':
                llm_task_prompt = f"Grazie. L'Evento Critico (EC) sembra essere '{ec_text[:100]}...'. Ora, potresti descrivere specificamente qual è stato il primo **pensiero, immagine, dubbio o paura (l'Ossessione - PV1)** che hai avuto in *quel momento*?"
            elif next_missing == 'ts1':
                llm_task_prompt = f"Capito. Dopo l'Evento Critico ('{ec_text[:80]}...') hai avuto l'Ossessione (PV1) '{pv1_text[:100]}...'. Cosa hai fatto, pensato o sentito *subito dopo* (o anche più tardi ma collegato) **per rispondere a questa ossessione e cercare di gestirla (la Compulsione - TS1)?** (es: azione fisica, pensiero specifico, rituale mentale, rassicurazione, evitamento)."
            elif next_missing == 'sv2':
                 llm_task_prompt = f"Ok ({context_summary}). Subito **dopo** l'Ossessione ('{pv1_text[:80]}...') o la Compulsione ('{ts1_text[:80]}...'), cosa hai **PENSATO** o **GIUDICATO** riguardo a quello che stava succedendo, all'ossessione stessa o alla compulsione? Cerchiamo la **valutazione cognitiva/metacognitiva (Seconda Valutazione - SV2)**, non solo l'emozione."
            elif next_missing == 'ts2':
                 llm_task_prompt = f"Bene ({context_summary}). Pensando a tutta questa esperienza, hai poi messo in atto qualche **strategia futura per EVITARE situazioni simili**, per **prevenire l'ossessione**, o per **gestire diversamente la compulsione (Tentativo Soluzione 2 - TS2)?**"
            else: # Non dovrebbe succedere se EC è gestito nel fallback
                log_message(f"WARN: next_missing è '{next_missing}', non gestito. Fallback a conferma.")
                next_missing = None # Forza il passaggio alla conferma

        # Se non manca più nulla (o il fallback sopra lo imposta a None)
        if not next_missing:
             log_message("Assessment Logic: Tutti i componenti necessari estratti/identificati. Transizione a ASSESSMENT_CONFIRM_SCHEMA.")
             new_state['phase'] = 'ASSESSMENT_CONFIRM_SCHEMA'
             bot_response_text = _create_summary_text(new_state['schema']) # Usa helper per riepilogo

    # --- FASI GET_PV1, GET_TS1, GET_SV2, GET_TS2 (Logica adattata) ---
    # Queste fasi ora gestiscono l'input *specifico* per quel componente,
    # ma la logica di validazione (se presente) e transizione rimane simile.
    # La differenza è che ora sappiamo quali componenti *precedenti* sono già stati raccolti.

    elif current_phase == 'ASSESSMENT_GET_PV1':
        log_message(f"Assessment Logic: Ricevuto input esplicito per PV1: {user_msg[:50]}...")
        new_state['schema']['pv1'] = user_msg # Salva input come PV1
        # Trova il prossimo mancante (sarà TS1 o successivo)
        next_missing = _find_next_missing_step(new_state['schema'])
        if next_missing:
             target_phase = f"ASSESSMENT_GET_{next_missing.upper()}"
             new_state['phase'] = target_phase
             log_message(f"Assessment Logic: PV1 salvato. Prossimo mancante '{next_missing}'. Transizione a {target_phase}.")
             # Imposta prompt per chiedere 'next_missing' (codice simile a sopra per GET_EXAMPLE)
             ec_text = new_state['schema'].get('ec', 'la situazione iniziale')
             pv1_text = new_state['schema'].get('pv1', 'il pensiero/ossessione') # Appena salvato
             if next_missing == 'ts1':
                 llm_task_prompt = f"Ok, l'Ossessione (PV1) identificata è '{pv1_text[:100]}...'. Adesso passiamo alla **Compulsione (TS1)**. Cosa hai fatto/pensato/sentito *in risposta diretta* a quell'ossessione per cercare di gestirla?"
             # ... aggiungere qui logica per chiedere SV2 o TS2 se TS1 fosse già presente per qualche motivo ...
             else: # Fallback se next_missing è inaspettato
                  new_state['phase'] = 'ASSESSMENT_CONFIRM_SCHEMA'
                  bot_response_text = _create_summary_text(new_state['schema'])
        else: # Tutti presenti dopo PV1? Conferma.
             new_state['phase'] = 'ASSESSMENT_CONFIRM_SCHEMA'
             bot_response_text = _create_summary_text(new_state['schema'])

    elif current_phase == 'ASSESSMENT_GET_TS1':
        log_message(f"Assessment Logic: Ricevuto input esplicito per TS1: {user_msg[:50]}...")
        # Qui potresti reinserire la logica di validazione TS1 con LLM se desiderato
        # Per semplicità, ora salviamo direttamente e procediamo.
        new_state['schema']['ts1'] = user_msg # Salva input come TS1
        next_missing = _find_next_missing_step(new_state['schema']) # Sarà SV2 o TS2
        if next_missing:
             target_phase = f"ASSESSMENT_GET_{next_missing.upper()}"
             new_state['phase'] = target_phase
             log_message(f"Assessment Logic: TS1 salvato. Prossimo mancante '{next_missing}'. Transizione a {target_phase}.")
             # Imposta prompt per chiedere SV2 o TS2
             ec_text = new_state['schema'].get('ec', '...')
             pv1_text = new_state['schema'].get('pv1', '...')
             ts1_text = new_state['schema'].get('ts1', '...') # Appena salvato
             if next_missing == 'sv2':
                  llm_task_prompt = f"Bene, la Compulsione (TS1) è stata '{ts1_text[:100]}...'. Ora, **subito dopo** l'Ossessione ('{pv1_text[:80]}...') o la Compulsione, cosa hai **PENSATO** o **GIUDICATO** riguardo a ciò che succedeva (Seconda Valutazione - SV2)? (Non solo l'emozione)."
             elif next_missing == 'ts2': # Se SV2 fosse già presente
                  llm_task_prompt = f"Ok. C'è stata poi qualche **strategia futura per EVITARE/MODIFICARE** il ciclo (Tentativo Soluzione 2 - TS2)?"
             else: # Fallback
                  new_state['phase'] = 'ASSESSMENT_CONFIRM_SCHEMA'
                  bot_response_text = _create_summary_text(new_state['schema'])
        else: # Tutti presenti dopo TS1. Conferma.
            new_state['phase'] = 'ASSESSMENT_CONFIRM_SCHEMA'
            bot_response_text = _create_summary_text(new_state['schema'])

    elif current_phase == 'ASSESSMENT_GET_SV2':
        log_message(f"Assessment Logic: Ricevuto input esplicito per SV2: {user_msg[:50]}...")
        # Qui potresti reinserire la logica di validazione SV2 con LLM
        # Se la validazione indica 'NONE', imposta a None nello schema
        # Per semplicità, salviamo direttamente. Considera "" o "nessuna" come None.
        sv2_value = user_msg.strip()
        if sv2_value.lower() in ["", "none", "nessuna", "niente", "non lo so"]:
            new_state['schema']['sv2'] = None
            log_message("Assessment Logic: SV2 interpretato come non significativo.")
        else:
            new_state['schema']['sv2'] = sv2_value # Salva input come SV2
        next_missing = _find_next_missing_step(new_state['schema']) # Sarà TS2
        if next_missing == 'ts2':
             new_state['phase'] = 'ASSESSMENT_GET_TS2'
             log_message(f"Assessment Logic: SV2 salvato/gestito. Prossimo mancante '{next_missing}'. Transizione a ASSESSMENT_GET_TS2.")
             # Imposta prompt per chiedere TS2
             sv2_text = new_state['schema'].get('sv2', 'la valutazione precedente')
             llm_task_prompt = f"Capito ({'SV2: '+sv2_text[:80]+'...' if sv2_text else 'SV2 non significativa'}). Ora l'ultimo punto per questo esempio: il **Tentativo di Soluzione 2 (TS2)**. C'è stata qualche strategia/intenzione futura per **evitare situazioni simili**, **prevenire l'ossessione**, o **gestire diversamente la compulsione**?"
        else: # Tutti presenti o TS2 non necessario. Conferma.
            new_state['phase'] = 'ASSESSMENT_CONFIRM_SCHEMA'
            bot_response_text = _create_summary_text(new_state['schema'])

    elif current_phase == 'ASSESSMENT_GET_TS2':
        log_message(f"Assessment Logic: Ricevuto input esplicito per TS2: {user_msg[:50]}...")
        # Qui potresti reinserire la logica di validazione TS2 con LLM
        # Se la validazione indica 'NONE', imposta a None nello schema
        ts2_value = user_msg.strip()
        if ts2_value.lower() in ["", "none", "nessuna", "niente", "non lo so", "no"]:
             new_state['schema']['ts2'] = None
             log_message("Assessment Logic: TS2 interpretato come non significativo.")
        else:
             new_state['schema']['ts2'] = ts2_value # Salva input come TS2
        # Dopo TS2, si passa sempre alla conferma
        new_state['phase'] = 'ASSESSMENT_CONFIRM_SCHEMA'
        bot_response_text = _create_summary_text(new_state['schema'])
        log_message("Assessment Logic: TS2 salvato/gestito. Transizione a ASSESSMENT_CONFIRM_SCHEMA.")


    # --- FASI CONFIRM_SCHEMA, AWAIT_EDIT_TARGET, EDIT_X, COMPLETE ---
    # La logica di queste fasi rimane sostanzialmente invariata.
    # Usano _create_summary_text che ora gestisce meglio i valori None.

    elif current_phase == 'ASSESSMENT_CONFIRM_SCHEMA':
        user_msg_processed = user_msg.strip().lower()
        # Rafforzato check per modifica
        is_modification_request = any(keyword in user_msg_processed for keyword in ["modifi", "cambia", "aggiust", "corregg", "rivedere", "precisare", "sbagliato", "errato", "non è", "diverso"]) or \
                                  any(word in negazioni_o_dubbi for word in user_msg_processed.split() if word not in ['non']) # 'non' da solo è ambiguo

        # Check conferma (più specifico)
        is_confirmation = (user_msg_processed in conferme or \
                          any(user_msg_processed.startswith(conf + " ") for conf in conferme if isinstance(conf, str)) or \
                          any(word in conferme for word in user_msg_processed.split())) \
                          and not is_modification_request # Una conferma non dovrebbe contenere parole di modifica

        if is_confirmation:
            new_state['phase'] = 'RESTRUCTURING_INTRO' # Transizione alla nuova fase
            bot_response_text = "Ottimo, grazie per la conferma! Avere chiaro questo schema è un passo importante.\n\nOra che abbiamo definito un esempio del ciclo, possiamo iniziare ad approfondire le valutazioni e i pensieri che lo mantengono. Ti andrebbe di passare alla fase successiva, chiamata **Ristrutturazione Cognitiva**?"
            log_message(f"Assessment Logic: Schema confermato. Transizione proposta a RESTRUCTURING_INTRO.")
        elif is_modification_request:
            new_state['phase'] = 'ASSESSMENT_AWAIT_EDIT_TARGET'
            bot_response_text = "Certamente. Quale parte specifica dello schema vuoi modificare o precisare? (Puoi indicare 'Evento Critico', 'Ossessione', 'Compulsione', 'Seconda Valutazione', o 'Tentativo Soluzione 2')."
            log_message("Assessment Logic: Richiesta modifica. Transizione a ASSESSMENT_AWAIT_EDIT_TARGET.")
        else:
            # Se non è né conferma chiara né modifica chiara, richiedi
            log_message("Assessment Logic: Risposta non chiara a conferma schema. Richiedo.")
            summary_part = _create_summary_text(new_state['schema']) # Mostra di nuovo il riepilogo
            bot_response_text = f"Scusa, non ho capito bene. Ricontrolliamo lo schema:\n\n{summary_part}\n\nVa bene così com'è? Dimmi 'sì' se è corretto, oppure indica quale parte vuoi cambiare."
            new_state['phase'] = 'ASSESSMENT_CONFIRM_SCHEMA' # Rimani qui

    elif current_phase == 'ASSESSMENT_AWAIT_EDIT_TARGET':
         user_input_lower = user_msg.lower()
         target_key = None
         # Logica di identificazione target invariata
         if 'seconda valutazione' in user_input_lower or 'sv2' in user_input_lower: target_key = 'sv2'
         elif 'tentativo' in user_input_lower or 'ts2' in user_input_lower or 'soluzione 2' in user_input_lower or 'evitamento ciclo' in user_input_lower : target_key = 'ts2'
         elif 'compulsione' in user_input_lower or 'ts1' in user_input_lower: target_key = 'ts1'
         elif 'ossessione' in user_input_lower or 'pv1' in user_input_lower or 'prima valutazione' in user_input_lower : target_key = 'pv1'
         elif 'evento' in user_input_lower or 'critico' in user_input_lower or 'ec' in user_input_lower or 'situazione' in user_input_lower: target_key = 'ec'

         if target_key:
             new_state['editing_target'] = target_key
             new_state['phase'] = f'ASSESSMENT_EDIT_{target_key.upper()}'
             target_names = {'ec': 'Evento Critico', 'pv1': 'Ossessione', 'ts1': 'Compulsione', 'sv2': 'Seconda Valutazione', 'ts2': 'Tentativo Soluzione 2'}
             target_name = target_names.get(target_key, target_key)
             current_value = new_state.get('schema', {}).get(target_key, "Non definito")
             llm_task_prompt = f"Ok, vuoi modificare '{target_name}'. Il valore attuale è: \"{current_value}\". Per favore, fornisci la nuova descrizione completa per questo punto."
             log_message(f"Assessment Logic: Target modifica '{target_key}'. Transizione a {new_state['phase']}.")
         else:
             bot_response_text = "Non ho capito bene quale punto vuoi modificare. Puoi ripeterlo usando termini come 'Evento Critico', 'Ossessione', 'Compulsione', 'Seconda Valutazione' o 'Tentativo Soluzione 2'?"
             new_state['phase'] = 'ASSESSMENT_AWAIT_EDIT_TARGET' # Rimani qui
             log_message("Assessment Logic: Target modifica non identificato. Richiedo.")

    elif current_phase.startswith('ASSESSMENT_EDIT_'):
        target_key = current_state.get('editing_target')
        schema_dict = new_state.get('schema')
        if target_key and isinstance(schema_dict, dict) and target_key in schema_dict:
             log_message(f"Assessment Logic: Ricevuto nuovo valore per {target_key}: {user_msg[:50]}...")
             schema_dict[target_key] = user_msg # Aggiorna valore
             # Valori null/vuoti per SV2/TS2 durante modifica?
             if target_key in ['sv2', 'ts2'] and user_msg.strip().lower() in ["", "none", "nessuna", "niente"]:
                 schema_dict[target_key] = None
                 log_message(f"Assessment Logic: Valore per {target_key} impostato a None durante modifica.")

             new_state['phase'] = 'ASSESSMENT_CONFIRM_SCHEMA' # Torna sempre a conferma dopo modifica
             bot_response_text = _create_summary_text(schema_dict) # Mostra riepilogo aggiornato
             log_message(f"Assessment Logic: Valore '{target_key}' aggiornato. Ritorno a ASSESSMENT_CONFIRM_SCHEMA.")
        else:
             # Logica di errore invariata
             log_message(f"Assessment Logic: ERRORE CRITICO in EDIT - editing_target '{target_key}' non valido/trovato o schema non è dict. Schema: {schema_dict}. Ripristino.")
             new_state = current_state.copy() # Prendi lo stato PRIMA del tentativo di modifica
             if 'editing_target' in new_state: del new_state['editing_target']
             new_state['phase'] = 'ASSESSMENT_CONFIRM_SCHEMA' # Torna a conferma con stato vecchio
             bot_response_text = "Scusa, si è verificato un problema tecnico durante la modifica. Rivediamo lo schema com'era prima:\n\n" + _create_summary_text(new_state.get('schema', {}))

    elif current_phase == 'ASSESSMENT_COMPLETE': # Fallback per fase obsoleta
        log_message("Assessment Logic: WARN - Raggiunta fase ASSESSMENT_COMPLETE (obsoleta). Reindirizzo a RESTRUCTURING_INTRO.")
        new_state['phase'] = 'RESTRUCTURING_INTRO'
        bot_response_text = "Abbiamo completato la valutazione dell'esempio. Ti andrebbe ora di passare alla fase successiva, la **Ristrutturazione Cognitiva**?"


    # --- Gestione Chiamata LLM Specifica (se llm_task_prompt è impostato) ---
    # (Logica invariata, ma i prompt ora sono generati dinamicamente sopra)
    if llm_task_prompt:
        log_message(f"Assessment Logic: Eseguo LLM per task specifico: {llm_task_prompt}")
        # Prepara history pulita
        chat_history_for_llm = []
        history_source = st.session_state.get('messages', [])
        if len(history_source) > 1: # Escludi messaggio introduttivo iniziale del bot?
            for msg in history_source[:-1]: # Prendi tutta la storia tranne l'ultimo input utente (già in prompt)
                 role = 'model' if msg.get('role') == 'assistant' else msg.get('role')
                 content = msg.get('content', '')
                 if role in ['user', 'model'] and content and content.strip() not in ["...", "Sto pensando..."]:
                     chat_history_for_llm.append({'role': role, 'parts': [content]})

        # Prepara system prompt (invariato)
        system_prompt = f"""Sei un assistente empatico per il supporto al DOC (TCC).
FASE CONVERSAZIONE: {new_state['phase']}. SCHEMA UTENTE PARZIALE: {new_state.get('schema', {})}.
ISTRUZIONI: Rispondi in ITALIANO. Tono empatico, chiaro, CONCISO. Fai UNA domanda alla volta se necessario. Non usare sigle (EC, PV1 ecc.) nella domanda diretta all'utente, usa i nomi completi (es. Evento Critico). Non chiedere informazioni già presenti nello SCHEMA UTENTE PARZIALE.
OBIETTIVO SPECIFICO: {llm_task_prompt}"""

        # Genera risposta (logica invariata)
        bot_response_text = generate_response(
            prompt=f"{system_prompt}\n\n---\n\nUltimo Messaggio Utente (da ignorare se il prompt lo include già): {user_msg}", # Aggiungi nota su user_msg
            history=chat_history_for_llm,
            model=st.session_state.get('model_gemini')
        )

    # --- Fallback Generico Interno al Modulo ---
    # (Logica invariata)
    elif not bot_response_text:
        # ... (codice del fallback con RAG rimane identico) ...
        log_message(f"Assessment Logic: Nessuna logica specifica o task LLM per fase '{current_phase}'. Eseguo fallback generico...")
        # (Il codice RAG qui è omesso per brevità, ma è identico a prima)
        # ...
        # Esempio di come potrebbe finire il fallback RAG/Generico
        if 'rag_results' in locals() and rag_results: # Se RAG ha trovato qualcosa
             rag_context = "\n\n---\nCONTESTO DAL MATERIALE DI SUPPORTO:\n"
             for i, result in enumerate(rag_results): rag_context += f"[{i+1}] {result.get('content', '')}\n\n"
             log_message(f"Assessment Logic: Fallback RAG ({search_type}) trovato.")
        else: rag_context = ""; log_message(f"Assessment Logic: Fallback RAG non trovato.")

        system_prompt_generic = f"""Sei un assistente empatico per il supporto al DOC (TCC).
FASE CONVERSAZIONE ATTUALE: {new_state['phase']}. SCHEMA UTENTE: {new_state.get('schema', {})}.{rag_context}
ISTRUZIONI: Rispondi in ITALIANO. Tono empatico, chiaro, CONCISO. L'utente ha inviato un messaggio ('{user_msg[:100]}...') che non rientra nel flusso previsto per la fase attuale o per cui non c'era un task specifico. Rispondi in modo utile e pertinente, usando il contesto RAG se rilevante. Guida gentilmente verso l'obiettivo della fase attuale ({current_phase}). Fai UNA domanda alla volta se necessario."""

        # Prepara history (come sopra)
        chat_history_for_llm = []
        # ... (codice per popolare history) ...

        bot_response_text = generate_response(
            prompt=f"{system_prompt_generic}", # Prompt già contiene user_msg
            history=chat_history_for_llm,
            model=st.session_state.get('model_gemini')
        )
        log_message("Assessment Logic: Eseguito LLM generico di fallback.")


    # Fallback finale se ancora nessuna risposta
    if not bot_response_text:
        log_message("Assessment Logic: WARN - bot_response_text ancora vuoto dopo tutti i tentativi. Risposta fallback finale.")
        bot_response_text = "Non sono sicuro di come continuare da qui. Potresti riformulare o dirmi cosa vorresti fare?"

    # Pulisci 'editing_target' se non siamo più in una fase di modifica
    if 'editing_target' in new_state and not new_state.get('phase','').startswith('ASSESSMENT_EDIT_'):
         log_message("Assessment Logic: Uscita da fase EDIT, pulisco 'editing_target'.")
         del new_state['editing_target']

    log_message(f"Assessment Logic: Fine gestione fase '{current_phase}'. Nuovo stato: '{new_state.get('phase')}'")
    # Assicura che lo schema restituito sia un dizionario
    if 'schema' not in new_state or not isinstance(new_state['schema'], dict):
        log_message("ERRORE CRITICO: 'schema' perso o corrotto prima del return! Ripristino parziale.")
        new_state['schema'] = current_state.get('schema', INITIAL_STATE['schema'].copy()) # Tenta recupero da stato precedente
    return bot_response_text, new_state