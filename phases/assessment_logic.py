# filename: docBot_Stages/phases/assessment_logic.py
# phases/assessment_logic.py (Struttura Modulare a Fasi)
# CORRETTO: Aggiunto 'import re' mancante.
# AGGIORNATO: Estrazione iniziale in ASSESSMENT_GET_EXAMPLE semplificata (solo EC, PV1, TS1).
# AGGIORNATO: Aggiunta nuova fase ASSESSMENT_CONFIRM_FIRST_PART per conferma intermedia.
# AGGIORNATO: Mantenuta validazione LLM specifica per input in ASSESSMENT_GET_SV2.
# AGGIORNATO: Logica di EDIT_X per tornare alla fase di conferma corretta.

import streamlit as st
import time
import traceback
import json # Importato per parsing JSON
import re   # Import per espressioni regolari

# Importa funzioni e costanti necessarie
from utils import log_message
from llm_interface import generate_response
from rag_utils import search_global_rag, search_step_rag
from config import CONFERME, NEGAZIONI_O_DUBBI, PHASE_TO_CHAPTER_KEY_MAP, INITIAL_STATE

# --- Funzione Helper per creare il testo del riepilogo COMPLETO ---
def _create_summary_text(schema):
    """Genera il testo formattato per il riepilogo COMPLETO dello schema."""
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

# --- Funzione Helper per creare il testo del riepilogo PRIMA PARTE ---
def _create_first_part_summary_text(schema):
    """Genera il testo formattato per il riepilogo della PRIMA PARTE (EC, PV1, TS1)."""
    ec = schema.get('ec', 'N/D')
    pv1 = schema.get('pv1', 'N/D')
    ts1 = schema.get('ts1', 'N/D')

    # Gestisce il caso in cui TS1 non sia stato ancora identificato
    ts1_display = ts1 if ts1 else "(Compulsione non ancora identificata)"

    summary = f"""Ok, grazie. Dalla tua descrizione sembra che abbiamo identificato questa prima parte del ciclo:

* **Evento Critico (EC):** {ec}
* **Ossessione (PV1):** {pv1}
* **Compulsione (TS1):** {ts1_display}

Ti sembra che descriva correttamente l'inizio dell'esperienza? Possiamo andare avanti a esplorare cosa succede dopo (valutazioni e strategie future, che potrebbero esserci o meno)?
(Puoi dire 'sì' o indicare cosa modificare in questa prima parte)"""
    return summary


# --- Funzione Helper per Pulire Risposta LLM JSON ---
# (Invariata)
def _clean_llm_json_response(llm_response_text):
    """Tenta di estrarre un blocco JSON pulito dalla risposta dell'LLM."""
    if not llm_response_text: return "" # Gestisce input None o vuoto
    try:
        match = re.search(r"```json\s*(\{.*?\})\s*```", llm_response_text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        match = re.search(r"```\s*(\{.*?\})\s*```", llm_response_text, re.DOTALL)
        if match:
            return match.group(1).strip()
        stripped_response = llm_response_text.strip()
        if stripped_response.startswith('{') and stripped_response.endswith('}'):
             try:
                 json.loads(stripped_response)
                 return stripped_response
             except json.JSONDecodeError:
                 pass
        log_message("WARN: Pulizia JSON non ha trovato ```json o ```. Uso testo grezzo.")
        return stripped_response
    except Exception as e:
        log_message(f"ERRORE in _clean_llm_json_response: {e}")
        return llm_response_text

# --- Funzione Helper per Trovare il Prossimo Passo Mancante (Usata da GET_X e Conferma Finale) ---
# (Invariata)
def _find_next_missing_step(schema):
    """
    Identifica la prossima fase GET necessaria basandosi sullo schema attuale.
    Restituisce la chiave del componente mancante (es. 'pv1', 'ts1') o None se completo.
    """
    if not isinstance(schema, dict):
        log_message("ERRORE CRITICO: _find_next_missing_step ha ricevuto uno schema non valido.")
        return 'ec'
    if not schema.get('ec'): return 'ec'
    if not schema.get('pv1'): return 'pv1'
    if not schema.get('ts1'): return 'ts1'
    if not schema.get('sv2'): return 'sv2'
    if not schema.get('ts2'): return 'ts2'
    return None

# --- Funzione Handler Principale per le Fasi di Assessment ---
def handle(user_msg, current_state):
    """
    Gestisce la logica per tutte le fasi relative all'Assessment.
    Include analisi semplificata, conferma intermedia e validazione SV2.
    """
    new_state = current_state.copy()
    if 'schema' not in new_state or not isinstance(new_state.get('schema'), dict):
        log_message("WARN: 'schema' mancante o non dict in new_state. Reinizializzo.")
        new_state['schema'] = INITIAL_STATE['schema'].copy()

    current_phase = new_state.get('phase', 'START')
    log_message(f"Assessment Logic: Gestione fase '{current_phase}'")

    bot_response_text = ""
    llm_task_prompt = None

    conferme = CONFERME
    negazioni_o_dubbi = NEGAZIONI_O_DUBBI
    negazioni_esplicite = ["", "none", "nessuna", "niente", "non lo so", "non saprei", "no"]

    # --- Logica Specifica per Sotto-Fasi dell'Assessment ---

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
             llm_task_prompt = "Perfetto. Allora, prova a raccontarmi una situazione concreta e recente in cui hai provato ansia, disagio o hai avuto pensieri che ti preoccupavano legati al DOC. Descrivi semplicemente cosa è successo e cosa hai pensato o fatto."
             log_message("Assessment Logic: Transizione ASSESSMENT_INTRO -> ASSESSMENT_GET_EXAMPLE (con richiesta aperta).")
        else:
             new_state['phase'] = 'ASSESSMENT_GET_EXAMPLE'
             log_message("Assessment Logic: Input non conferma diretta, assumo sia inizio Esempio -> ASSESSMENT_GET_EXAMPLE.")

    # --- ASSESSMENT_GET_EXAMPLE (Estrazione Semplificata EC, PV1, TS1) ---
    elif current_phase == 'ASSESSMENT_GET_EXAMPLE':
        log_message(f"Assessment Logic: Ricevuto input in ASSESSMENT_GET_EXAMPLE: '{user_msg[:100]}...'")
        log_message("Assessment Logic: Avvio analisi LLM semplificata (EC, PV1, TS1)...")

        # 1. Prompt Semplificato
        extraction_prompt = f"""Analizza attentamente il seguente messaggio dell'utente, che descrive un'esperienza legata al DOC:
        \"\"\"
        {user_msg}
        \"\"\"
        Il tuo compito è identificare e separare i seguenti componenti INIZIALI dello schema DOC, se sono chiaramente presenti nel testo:
        1.  **EC (Evento Critico):** La situazione specifica, l'evento esterno o interno che ha innescato il ciclo.
        2.  **PV1 (Prima Valutazione/Ossessione):** Il primo pensiero intrusivo, dubbio, immagine o paura significativa sorta in risposta all'EC.
        3.  **TS1 (Tentativo Soluzione 1/Compulsione):** La reazione comportamentale o mentale (rituale, controllo, rassicurazione, evitamento, anche differito) messa in atto *in risposta diretta* a PV1 per gestirla.

        Restituisci il risultato ESATTAMENTE nel seguente formato JSON:
        {{
          "ec": "Testo estratto dell'Evento Critico",
          "pv1": "Testo estratto della Prima Valutazione",
          "ts1": "Testo estratto della Compulsione/Tentativo Soluzione 1"
        }}

        Se un componente NON è chiaramente identificabile nel messaggio fornito, imposta il suo valore su **null** o su una **stringa vuota**. Sii conciso. Se non identifichi nemmeno l'EC, restituisci null per EC. Non cercare SV2 o TS2 in questo passaggio.
        """

        # 2. Chiama LLM
        extracted_components = {'ec': None, 'pv1': None, 'ts1': None} # Solo i primi 3
        llm_extraction_response = None
        parsing_ok = False
        try:
            llm_extraction_response = generate_response(
                prompt=extraction_prompt, history=[], model=st.session_state.get('model_gemini')
            )
            log_message(f"Assessment Logic: Risposta LLM grezza per estrazione semplificata: {llm_extraction_response}")

            # 3. Pulisci e Parsa JSON (solo EC, PV1, TS1)
            if llm_extraction_response:
                clean_response = _clean_llm_json_response(llm_extraction_response)
                try:
                    parsed_data = json.loads(clean_response)
                    if isinstance(parsed_data, dict):
                        extracted_components['ec'] = parsed_data.get("ec") if parsed_data.get("ec") else None
                        extracted_components['pv1'] = parsed_data.get("pv1") if parsed_data.get("pv1") else None
                        extracted_components['ts1'] = parsed_data.get("ts1") if parsed_data.get("ts1") else None
                        log_message(f"Assessment Logic: Estrazione JSON semplificata riuscita - Dati: {extracted_components}")
                        parsing_ok = True
                    else:
                        log_message("Assessment Logic: WARN - Risposta LLM (sempl.) pulita non è un dizionario JSON valido.")
                except json.JSONDecodeError as json_err:
                    log_message(f"Assessment Logic: ERRORE parsing JSON (sempl.) da LLM: {json_err}. Risposta LLM pulita: {clean_response}")
            else:
                log_message("Assessment Logic: WARN - Risposta LLM (sempl.) per estrazione è vuota.")

        except Exception as e:
            log_message(f"Assessment Logic: ERRORE durante chiamata LLM o processing (sempl.): {e}\n{traceback.format_exc()}")

        # 4. Gestisci Fallback o Successo
        if not parsing_ok:
            # Fallback: Usa intero messaggio come EC, resetta il resto
            log_message("Assessment Logic: Fallback (causa errore estrazione/parsing sempl.) - Uso l'intero user_msg come EC.")
            new_state['schema'] = INITIAL_STATE['schema'].copy()
            new_state['schema']['ec'] = user_msg
            # Transizione per chiedere PV1 esplicitamente
            new_state['phase'] = 'ASSESSMENT_GET_PV1'
            log_message(f"Assessment Logic: Transizione fallback a {new_state['phase']}.")
            ec_text = new_state['schema'].get('ec', 'la situazione descritta')
            llm_task_prompt = f"Grazie per aver descritto la situazione: '{ec_text[:100]}...'. Ora vorrei capire l'**Ossessione (PV1)**. Con tono empatico, chiedi specificamente quale è stato il primo pensiero, immagine, dubbio o paura (l'ossessione) che ha avuto in *quel momento*."

        else:
            # Successo: Salva EC, PV1, TS1 estratti
            for key, value in extracted_components.items():
                if value:
                    new_state['schema'][key] = value
            log_message(f"Assessment Logic: Schema aggiornato dopo estrazione semplificata: {new_state['schema']}")

            # 5. Transizione alla NUOVA fase di conferma intermedia
            new_state['phase'] = 'ASSESSMENT_CONFIRM_FIRST_PART'
            log_message(f"Assessment Logic: Transizione a {new_state['phase']}.")
            # La risposta verrà generata dalla logica della nuova fase
            bot_response_text = _create_first_part_summary_text(new_state['schema'])


    # --- NUOVA FASE: ASSESSMENT_CONFIRM_FIRST_PART ---
    elif current_phase == 'ASSESSMENT_CONFIRM_FIRST_PART':
        log_message(f"Assessment Logic: Gestione fase '{current_phase}'")
        user_msg_processed = user_msg.strip().lower()

        # Verifica se è richiesta modifica (logica simile a CONFIRM_SCHEMA)
        is_modification_request = any(keyword in user_msg_processed for keyword in ["modifi", "cambia", "aggiust", "corregg", "rivedere", "precisare", "sbagliato", "errato", "non è", "diverso"]) or \
                                  any(word in negazioni_o_dubbi for word in user_msg_processed.split() if word not in ['non'])

        # Verifica se è conferma
        is_confirmation = (user_msg_processed in conferme or \
                          any(user_msg_processed.startswith(conf + " ") for conf in conferme if isinstance(conf, str)) or \
                          any(word in conferme for word in user_msg_processed.split())) \
                          and not is_modification_request

        if is_confirmation:
            log_message("Assessment Logic: Prima parte (EC/PV1/TS1) confermata.")
            # Introduci SV2/TS2 e transiziona a GET_SV2
            new_state['phase'] = 'ASSESSMENT_GET_SV2'
            log_message(f"Assessment Logic: Transizione a {new_state['phase']}.")
            ec_text = new_state['schema'].get('ec', '...')
            pv1_text = new_state['schema'].get('pv1', '...')
            ts1_text = new_state['schema'].get('ts1', '...')
            llm_task_prompt = f"Perfetto, grazie. Ora esploriamo cosa succede dopo la Compulsione ('{ts1_text[:80]}...'). A volte, ci sono altri pensieri o valutazioni (Seconda Valutazione - SV2), e magari strategie per evitare il problema in futuro (Tentativo Soluzione 2 - TS2). Questi elementi non sono sempre presenti o evidenti. \n\nConcentriamoci sulla **Seconda Valutazione (SV2)**: subito **dopo** l'Ossessione ('{pv1_text[:80]}...') o la Compulsione ('{ts1_text[:80]}...'), cosa hai **PENSATO** o **GIUDICATO** riguardo a quello che stava succedendo, all'ossessione stessa, alla compulsione o alle sue conseguenze? (Non solo l'emozione)."

        elif is_modification_request:
            log_message("Assessment Logic: Richiesta modifica prima parte.")
            # Transiziona a AWAIT_EDIT_TARGET, memorizzando da dove veniamo
            new_state['originating_confirmation_phase'] = 'ASSESSMENT_CONFIRM_FIRST_PART' # Memorizza origine
            new_state['phase'] = 'ASSESSMENT_AWAIT_EDIT_TARGET'
            log_message(f"Assessment Logic: Transizione a {new_state['phase']} (da {current_phase}).")
            bot_response_text = "Certamente. Quale parte specifica di questa prima fase (Evento Critico, Ossessione, Compulsione) vuoi modificare o precisare?"

        else:
            # Risposta non chiara, richiedi conferma/modifica
            log_message("Assessment Logic: Risposta non chiara a conferma prima parte. Richiedo.")
            new_state['phase'] = 'ASSESSMENT_CONFIRM_FIRST_PART' # Rimani qui
            bot_response_text = "Scusa, non ho afferrato bene. Riguardando questa prima parte:\n\n" + \
                                _create_first_part_summary_text(new_state['schema']).split("Ok, grazie. ")[1] # Mostra di nuovo il riepilogo parziale


    # --- FASI GET (PV1, TS1) ---
    # Queste fasi ora vengono chiamate solo se l'estrazione iniziale fallisce o è incompleta per questi elementi

    elif current_phase == 'ASSESSMENT_GET_PV1':
        log_message(f"Assessment Logic: Ricevuto input esplicito per PV1: {user_msg[:50]}...")
        new_state['schema']['pv1'] = user_msg
        # Dopo aver ottenuto PV1, potremmo aver bisogno di TS1
        next_missing = _find_next_missing_step(new_state['schema'])
        if next_missing == 'ts1':
             new_state['phase'] = 'ASSESSMENT_GET_TS1'
             log_message(f"Assessment Logic: PV1 salvato. Prossimo mancante '{next_missing}'. Transizione a {new_state['phase']}.")
             pv1_text = new_state['schema'].get('pv1', '...')
             llm_task_prompt = f"Ok, l'Ossessione (PV1) identificata è '{pv1_text[:100]}...'. Adesso passiamo alla **Compulsione (TS1)**. Cosa hai fatto/pensato/sentito *in risposta diretta* a quell'ossessione per cercare di gestirla?"
        else:
            # Se TS1 è già presente (improbabile qui), o se manca solo SV2/TS2,
            # passiamo alla conferma della prima parte.
            new_state['phase'] = 'ASSESSMENT_CONFIRM_FIRST_PART'
            log_message(f"Assessment Logic: PV1 salvato. TS1 già presente o non necessario ora. Transizione a {new_state['phase']}.")
            bot_response_text = _create_first_part_summary_text(new_state['schema'])


    elif current_phase == 'ASSESSMENT_GET_TS1':
        log_message(f"Assessment Logic: Ricevuto input esplicito per TS1: {user_msg[:50]}...")
        new_state['schema']['ts1'] = user_msg
        # Dopo aver ottenuto TS1, la prima parte è completa. Passiamo alla conferma intermedia.
        new_state['phase'] = 'ASSESSMENT_CONFIRM_FIRST_PART'
        log_message(f"Assessment Logic: TS1 salvato. Transizione a {new_state['phase']}.")
        bot_response_text = _create_first_part_summary_text(new_state['schema'])


    # --- ASSESSMENT_GET_SV2 (CON VALIDAZIONE LLM) ---
    # Questa fase ora viene chiamata DOPO la conferma della prima parte
    elif current_phase == 'ASSESSMENT_GET_SV2':
        log_message(f"Assessment Logic: Ricevuto input per SV2: {user_msg[:50]}...")
        sv2_input = user_msg.strip()

        # 1. Controlla negazioni esplicite
        if sv2_input.lower() in negazioni_esplicite:
            log_message("Assessment Logic: SV2 interpretato come non significativo (negazione esplicita).")
            new_state['schema']['sv2'] = None
            # Passa a chiedere TS2
            new_state['phase'] = 'ASSESSMENT_GET_TS2'
            log_message("Assessment Logic: Transizione a ASSESSMENT_GET_TS2.")
            llm_task_prompt = f"Capito (SV2 non significativa). Ora l'ultimo punto: il **Tentativo di Soluzione 2 (TS2)**. C'è stata qualche strategia/intenzione futura per **evitare situazioni simili**, **prevenire l'ossessione**, o **gestire diversamente la compulsione**? Hai provato a resistere?"

        # 2. Se non è negazione, valida con LLM
        else:
            log_message("Assessment Logic: Avvio validazione LLM per SV2...")
            # (Validation prompt invariato)
            validation_prompt = f"""ANALISI RISPOSTA UTENTE PER SECONDA VALUTAZIONE (SV2)
            CONTESTO: Dopo Evento Critico (EC)="{new_state['schema'].get('ec', 'N/D')}", Ossessione (PV1)="{new_state['schema'].get('pv1', 'N/D')}", e Compulsione (TS1)="{new_state['schema'].get('ts1', 'N/D')}".
            DOMANDA POSTA ALL'UTENTE: Chiedeva la Seconda Valutazione (SV2) - il PENSIERO o GIUDIZIO (anche su conseguenze) dopo PV1/TS1, non solo l'emozione.
            RISPOSTA UTENTE DA ANALIZZARE: "{sv2_input}"

            TASK: La risposta dell'utente descrive effettivamente una Valutazione Cognitiva Secondaria (SV2)?
            - È un pensiero, un giudizio, una valutazione (anche metacognitiva), una riflessione sulle conseguenze? (es. "ho pensato fosse terribile", "mi sono giudicato stupido", "ho capito che non bastava", "questo significa che sono cattivo", "rischierò il licenziamento") -> VALIDO_SV2
            - È SOLO un'emozione (es. "ansia", "paura", "disgusto")? -> NON_VALIDO_SV2
            - È un'azione, un comportamento, un tentativo (anche fallito) di fare/non fare qualcosa? (es. "sono tornato indietro", "ho cercato di resistere", "ho controllato di nuovo") -> NON_VALIDO_SV2
            - È una negazione esplicita o "non lo so"? (es. "niente", "non ho pensato a nulla", "non saprei") -> NEGATIVO
            - È qualcos'altro di non pertinente? -> NON_VALIDO_SV2

            Output Atteso: Rispondi ESATTAMENTE con UNA delle seguenti stringhe: VALIDO_SV2, NON_VALIDO_SV2, NEGATIVO
            """
            try:
                validation_response = generate_response(
                    prompt=validation_prompt, history=[], model=st.session_state.get('model_gemini')
                ).strip().upper()
                log_message(f"Assessment Logic: Risultato validazione LLM per SV2: '{validation_response}'")

                # 3. Gestisci risultato validazione
                if validation_response == 'VALIDO_SV2':
                    log_message("Assessment Logic: SV2 validato come VALIDO.")
                    new_state['schema']['sv2'] = sv2_input # Salva SV2
                    # Passa a chiedere TS2
                    new_state['phase'] = 'ASSESSMENT_GET_TS2'
                    log_message("Assessment Logic: Transizione a ASSESSMENT_GET_TS2.")
                    sv2_text = new_state['schema'].get('sv2', 'la valutazione precedente')
                    llm_task_prompt = f"Capito (SV2: {sv2_text[:80]}...). Ora l'ultimo punto: il **Tentativo di Soluzione 2 (TS2)**. C'è stata qualche strategia/intenzione futura per **evitare situazioni simili**, **prevenire l'ossessione**, o **gestire diversamente la compulsione**? Hai provato a resistere?"

                elif validation_response == 'NEGATIVO':
                    log_message("Assessment Logic: SV2 validato come NEGATIVO.")
                    new_state['schema']['sv2'] = None
                    # Passa a chiedere TS2
                    new_state['phase'] = 'ASSESSMENT_GET_TS2'
                    log_message("Assessment Logic: Transizione a ASSESSMENT_GET_TS2.")
                    llm_task_prompt = f"Capito (SV2 non significativa). Ora l'ultimo punto: il **Tentativo di Soluzione 2 (TS2)**. C'è stata qualche strategia/intenzione futura per **evitare situazioni simili**, **prevenire l'ossessione**, o **gestire diversamente la compulsione**? Hai provato a resistere?"

                else: # NON_VALIDO_SV2 o risposta inattesa
                    log_message("Assessment Logic: SV2 validato come NON VALIDO. Richiedo.")
                    new_state['phase'] = 'ASSESSMENT_GET_SV2' # Rimani qui
                    # Prepara prompt per richiedere SV2
                    pv1_text = new_state['schema'].get('pv1', '...')
                    ts1_text = new_state['schema'].get('ts1', '...')
                    llm_task_prompt = f"Ok, grazie per la risposta ('{sv2_input[:80]}...'). Tuttavia, stiamo cercando specificamente la **Seconda Valutazione (SV2)**: un **pensiero**, un **giudizio** o una **valutazione** (anche sulle conseguenze) che hai avuto *dopo* l'ossessione ('{pv1_text[:80]}...') o la compulsione ('{ts1_text[:80]}...'). Non l'emozione o l'azione stessa. C'è stato un pensiero o giudizio specifico in quel momento? (Se non c'è stato o non ricordi, dimmi pure 'nessuno' o 'non ricordo')."

            except Exception as e:
                log_message(f"ERRORE durante validazione LLM per SV2: {e}. Richiedo.")
                new_state['phase'] = 'ASSESSMENT_GET_SV2' # Rimani qui in caso di errore
                llm_task_prompt = f"Scusa, ho avuto un problema nell'analizzare la tua risposta per la Seconda Valutazione. Potresti ripeterla o riformularla? Ricorda, cerchiamo un pensiero o un giudizio avuto dopo l'ossessione o la compulsione."

    # --- ASSESSMENT_GET_TS2 ---
    # Chiamato dopo GET_SV2
    elif current_phase == 'ASSESSMENT_GET_TS2':
        log_message(f"Assessment Logic: Ricevuto input esplicito per TS2: {user_msg[:50]}...")
        ts2_value = user_msg.strip()
        if ts2_value.lower() in negazioni_esplicite:
             new_state['schema']['ts2'] = None
             log_message("Assessment Logic: TS2 interpretato come non significativo.")
        else:
             new_state['schema']['ts2'] = ts2_value # Salva input come TS2
        # Dopo TS2, si passa alla conferma FINALE
        new_state['phase'] = 'ASSESSMENT_CONFIRM_SCHEMA'
        bot_response_text = _create_summary_text(new_state['schema']) # Riepilogo completo
        log_message("Assessment Logic: TS2 salvato/gestito. Transizione a ASSESSMENT_CONFIRM_SCHEMA.")


    # --- ASSESSMENT_CONFIRM_SCHEMA (Conferma Finale) ---
    # Chiamato dopo GET_TS2 o se si salta SV2/TS2
    elif current_phase == 'ASSESSMENT_CONFIRM_SCHEMA':
        log_message(f"Assessment Logic: Gestione fase '{current_phase}'")
        user_msg_processed = user_msg.strip().lower()
        is_modification_request = any(keyword in user_msg_processed for keyword in ["modifi", "cambia", "aggiust", "corregg", "rivedere", "precisare", "sbagliato", "errato", "non è", "diverso"]) or \
                                  any(word in negazioni_o_dubbi for word in user_msg_processed.split() if word not in ['non'])

        is_confirmation = (user_msg_processed in conferme or \
                          any(user_msg_processed.startswith(conf + " ") for conf in conferme if isinstance(conf, str)) or \
                          any(word in conferme for word in user_msg_processed.split())) \
                          and not is_modification_request

        if is_confirmation:
            new_state['phase'] = 'RESTRUCTURING_INTRO' # Transizione alla Ristrutturazione
            bot_response_text = "Ottimo, grazie per la conferma! Avere chiaro questo schema completo è un passo importante.\n\nOra che abbiamo definito un esempio del ciclo, possiamo iniziare ad approfondire le valutazioni e i pensieri che lo mantengono. Ti andrebbe di passare alla fase successiva, chiamata **Ristrutturazione Cognitiva**?"
            log_message(f"Assessment Logic: Schema COMPLETO confermato. Transizione proposta a RESTRUCTURING_INTRO.")
        elif is_modification_request:
            # Memorizza che veniamo dalla conferma finale
            new_state['originating_confirmation_phase'] = 'ASSESSMENT_CONFIRM_SCHEMA'
            new_state['phase'] = 'ASSESSMENT_AWAIT_EDIT_TARGET'
            log_message(f"Assessment Logic: Richiesta modifica schema completo. Transizione a {new_state['phase']}.")
            bot_response_text = "Certamente. Quale parte specifica dello schema completo (Evento Critico, Ossessione, Compulsione, Seconda Valutazione, Tentativo Soluzione 2) vuoi modificare o precisare?"
        else:
            log_message("Assessment Logic: Risposta non chiara a conferma schema completo. Richiedo.")
            summary_part = _create_summary_text(new_state['schema']) # Riepilogo completo
            bot_response_text = f"Scusa, non ho capito bene. Ricontrolliamo lo schema completo:\n\n{summary_part}\n\nVa bene così com'è? Dimmi 'sì' se è corretto, oppure indica quale parte vuoi cambiare."
            new_state['phase'] = 'ASSESSMENT_CONFIRM_SCHEMA' # Rimani qui


    # --- ASSESSMENT_AWAIT_EDIT_TARGET ---
    # Gestisce la richiesta di modifica proveniente da CONFIRM_FIRST_PART o CONFIRM_SCHEMA
    elif current_phase == 'ASSESSMENT_AWAIT_EDIT_TARGET':
         log_message(f"Assessment Logic: Gestione fase '{current_phase}'")
         user_input_lower = user_msg.lower()
         target_key = None
         # Logica di identificazione target invariata
         if 'seconda valutazione' in user_input_lower or 'sv2' in user_input_lower: target_key = 'sv2'
         elif 'tentativo' in user_input_lower or 'ts2' in user_input_lower or 'soluzione 2' in user_input_lower or 'evitamento ciclo' in user_input_lower : target_key = 'ts2'
         elif 'compulsione' in user_input_lower or 'ts1' in user_input_lower: target_key = 'ts1'
         elif 'ossessione' in user_input_lower or 'pv1' in user_input_lower or 'prima valutazione' in user_input_lower : target_key = 'pv1'
         elif 'evento' in user_input_lower or 'critico' in user_input_lower or 'ec' in user_input_lower or 'situazione' in user_input_lower: target_key = 'ec'

         # Verifica se il target è valido per la fase da cui si proviene
         origin_phase = current_state.get('originating_confirmation_phase', 'ASSESSMENT_CONFIRM_SCHEMA') # Default a schema completo
         allowed_targets = ['ec', 'pv1', 'ts1'] if origin_phase == 'ASSESSMENT_CONFIRM_FIRST_PART' else ['ec', 'pv1', 'ts1', 'sv2', 'ts2']

         if target_key and target_key in allowed_targets:
             new_state['editing_target'] = target_key
             new_state['phase'] = f'ASSESSMENT_EDIT_{target_key.upper()}'
             target_names = {'ec': 'Evento Critico', 'pv1': 'Ossessione', 'ts1': 'Compulsione', 'sv2': 'Seconda Valutazione', 'ts2': 'Tentativo Soluzione 2'}
             target_name = target_names.get(target_key, target_key)
             current_value = new_state.get('schema', {}).get(target_key, "Non definito")
             llm_task_prompt = f"Ok, vuoi modificare '{target_name}'. Il valore attuale è: \"{current_value}\". Per favore, fornisci la nuova descrizione completa per questo punto."
             log_message(f"Assessment Logic: Target modifica '{target_key}'. Transizione a {new_state['phase']}.")
         else:
             # Target non valido o non permesso per questa fase
             allowed_targets_text = ", ".join([t.upper() for t in allowed_targets])
             bot_response_text = f"Non ho capito bene quale punto vuoi modificare o non è possibile modificare quel punto ora. Puoi indicarmi uno tra: {allowed_targets_text}?"
             new_state['phase'] = 'ASSESSMENT_AWAIT_EDIT_TARGET' # Rimani qui
             log_message(f"Assessment Logic: Target modifica '{target_key}' non identificato o non permesso da {origin_phase}. Richiedo.")


    # --- ASSESSMENT_EDIT_X ---
    # Ora ritorna alla fase di conferma corretta (CONFIRM_FIRST_PART o CONFIRM_SCHEMA)
    elif current_phase.startswith('ASSESSMENT_EDIT_'):
        target_key = current_state.get('editing_target')
        schema_dict = new_state.get('schema')
        origin_phase = current_state.get('originating_confirmation_phase', 'ASSESSMENT_CONFIRM_SCHEMA') # Recupera origine

        if target_key and isinstance(schema_dict, dict) and target_key in schema_dict:
             log_message(f"Assessment Logic: Ricevuto nuovo valore per {target_key}: {user_msg[:50]}...")
             new_value = user_msg.strip()
             if target_key in ['sv2', 'ts2'] and new_value.lower() in negazioni_esplicite:
                 schema_dict[target_key] = None
                 log_message(f"Assessment Logic: Valore per {target_key} impostato a None durante modifica.")
             else:
                schema_dict[target_key] = new_value

             # Torna alla fase di conferma da cui è partita la modifica
             new_state['phase'] = origin_phase
             if origin_phase == 'ASSESSMENT_CONFIRM_FIRST_PART':
                 bot_response_text = _create_first_part_summary_text(schema_dict)
             else: # Default a conferma completa
                 bot_response_text = _create_summary_text(schema_dict)
             log_message(f"Assessment Logic: Valore '{target_key}' aggiornato. Ritorno a {origin_phase}.")
        else:
             # Errore critico
             log_message(f"Assessment Logic: ERRORE CRITICO in EDIT - editing_target '{target_key}' non valido/trovato o schema non è dict. Schema: {schema_dict}. Ripristino.")
             new_state = current_state.copy()
             new_state['phase'] = origin_phase # Torna all'origine anche in caso di errore
             if 'editing_target' in new_state: del new_state['editing_target']
             if origin_phase == 'ASSESSMENT_CONFIRM_FIRST_PART':
                 bot_response_text = "Scusa, problema tecnico nella modifica. Rivediamo la prima parte:\n\n" + _create_first_part_summary_text(new_state.get('schema', {})).split("Ok, grazie. ")[1]
             else:
                 bot_response_text = "Scusa, problema tecnico nella modifica. Rivediamo lo schema completo:\n\n" + _create_summary_text(new_state.get('schema', {}))

        # Pulisci sempre editing_target e originating_confirmation_phase dopo l'edit
        if 'editing_target' in new_state: del new_state['editing_target']
        if 'originating_confirmation_phase' in new_state: del new_state['originating_confirmation_phase']


    elif current_phase == 'ASSESSMENT_COMPLETE': # Obsoleto
        log_message("Assessment Logic: WARN - Raggiunta fase ASSESSMENT_COMPLETE (obsoleta). Reindirizzo a RESTRUCTURING_INTRO.")
        new_state['phase'] = 'RESTRUCTURING_INTRO'
        bot_response_text = "Abbiamo completato la valutazione dell'esempio. Ti andrebbe ora di passare alla fase successiva, la **Ristrutturazione Cognitiva**?"

    # --- Gestione Chiamata LLM Specifica (se llm_task_prompt è impostato) ---
    if llm_task_prompt:
        log_message(f"Assessment Logic: Eseguo LLM per task specifico: {llm_task_prompt}")
        chat_history_for_llm = []
        history_source = st.session_state.get('messages', [])
        if len(history_source) > 1:
            for msg in history_source[:-1]:
                 role = 'model' if msg.get('role') == 'assistant' else msg.get('role')
                 content = msg.get('content', '')
                 if role in ['user', 'model'] and content and content.strip() not in ["...", "Sto pensando..."]:
                     chat_history_for_llm.append({'role': role, 'parts': [content]})

        system_prompt = f"""Sei un assistente empatico per il supporto al DOC (TCC).
FASE CONVERSAZIONE: {new_state['phase']}. SCHEMA UTENTE PARZIALE: {new_state.get('schema', {})}.
ISTRUZIONI: Rispondi in ITALIANO. Tono empatico, chiaro, CONCISO. Fai UNA domanda alla volta se necessario. Non usare sigle (EC, PV1 ecc.) nella domanda diretta all'utente, usa i nomi completi (es. Evento Critico). Non chiedere informazioni già presenti nello SCHEMA UTENTE PARZIALE.
OBIETTIVO SPECIFICO: {llm_task_prompt}"""

        bot_response_text = generate_response(
            prompt=f"{system_prompt}\n\n---\n\nUltimo Messaggio Utente (da ignorare se il prompt lo include già): {user_msg}",
            history=chat_history_for_llm,
            model=st.session_state.get('model_gemini')
        )

    # --- Fallback Generico Interno al Modulo ---
    elif not bot_response_text:
        log_message(f"Assessment Logic: Nessuna logica specifica o task LLM per fase '{current_phase}'. Eseguo fallback generico...")
        # (Codice fallback RAG invariato, omesso per brevità)
        # ...
        # Esempio di come potrebbe finire il fallback RAG/Generico
        rag_context = "" # Simula assenza RAG per brevità
        system_prompt_generic = f"""Sei un assistente empatico per il supporto al DOC (TCC).
FASE CONVERSAZIONE ATTUALE: {new_state['phase']}. SCHEMA UTENTE: {new_state.get('schema', {})}.{rag_context}
ISTRUZIONI: Rispondi in ITALIANO. Tono empatico, chiaro, CONCISO. L'utente ha inviato un messaggio ('{user_msg[:100]}...') che non rientra nel flusso previsto per la fase attuale o per cui non c'era un task specifico. Rispondi in modo utile e pertinente, usando il contesto RAG se rilevante. Guida gentilmente verso l'obiettivo della fase attuale ({current_phase}). Fai UNA domanda alla volta se necessario."""
        chat_history_for_llm = [] # Simula history vuota per brevità
        bot_response_text = generate_response(
            prompt=f"{system_prompt_generic}",
            history=chat_history_for_llm,
            model=st.session_state.get('model_gemini')
        )
        log_message("Assessment Logic: Eseguito LLM generico di fallback.")


    # Fallback finale se ancora nessuna risposta
    if not bot_response_text:
        log_message("Assessment Logic: WARN - bot_response_text ancora vuoto dopo tutti i tentativi. Risposta fallback finale.")
        bot_response_text = "Non sono sicuro di come continuare da qui. Potresti riformulare o dirmi cosa vorresti fare?"

    # Pulisci stati temporanei se non siamo più in una fase rilevante
    if 'editing_target' in new_state and not new_state.get('phase','').startswith('ASSESSMENT_EDIT_'):
         log_message("Assessment Logic: Pulisco 'editing_target'.")
         del new_state['editing_target']
    if 'originating_confirmation_phase' in new_state and not new_state.get('phase','').startswith('ASSESSMENT_AWAIT_EDIT_TARGET'):
        log_message("Assessment Logic: Pulisco 'originating_confirmation_phase'.")
        del new_state['originating_confirmation_phase']


    log_message(f"Assessment Logic: Fine gestione fase '{current_phase}'. Nuovo stato: '{new_state.get('phase')}'")
    if 'schema' not in new_state or not isinstance(new_state['schema'], dict):
        log_message("ERRORE CRITICO: 'schema' perso o corrotto prima del return! Ripristino parziale.")
        new_state['schema'] = current_state.get('schema', INITIAL_STATE['schema'].copy())
    return bot_response_text, new_state
