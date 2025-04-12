# filename: docBot_Stages/phases/assessment_logic.py
# phases/assessment_logic.py (Struttura Modulare a Fasi)
# CORRETTO: Aggiunto 'import re' mancante.
# AGGIORNATO: Estrazione iniziale semplificata (EC, PV1, TS1).
# AGGIORNATO: Aggiunta fase ASSESSMENT_CONFIRM_FIRST_PART.
# AGGIORNATO: Mantenuta validazione LLM per input SV2 (prompt affinato v2).
# AGGIORNATO: Logica di EDIT_X per tornare alla fase di conferma corretta.
# NUOVO: Implementata funzione _summarize_component_clinically.
# AGGIORNATO: Prompt di _summarize_component_clinically modificato per maggiore fedeltà (v2).
# AGGIORNATO: Logica di fallback in _summarize_component_clinically per usare testo originale.

import streamlit as st
import time
import traceback
import json # Importato per parsing JSON
import re   # Import per espressioni regolari

# Importa funzioni e costanti necessarie
from utils import log_message
from llm_interface import generate_response # Importiamo per usare generate_response
from rag_utils import search_global_rag, search_step_rag
from config import CONFERME, NEGAZIONI_O_DUBBI, PHASE_TO_CHAPTER_KEY_MAP, INITIAL_STATE

# --- Funzione Helper per Sintesi Clinica (ma MOLTO Fedele) ---
def _summarize_component_clinically(component_key, user_text, schema_context):
    """
    Chiama l'LLM per rielaborare il testo dell'utente in una sintesi
    ESTREMAMENTE CONCISA e FEDELE per il componente specificato.
    In caso di fallimento della sintesi, restituisce il testo originale.
    """
    original_text_cleaned = user_text.strip().strip('"').strip("'")
    if not original_text_cleaned or not component_key:
        return original_text_cleaned

    log_message(f"Assessment Logic: Avvio sintesi ESTREMAMENTE fedele per {component_key.upper()}...")

    definitions = {
        'ec': "l'evento specifico (interno o esterno) che ha attivato il ciclo.",
        'pv1': "la prima valutazione (pensiero, dubbio, immagine, paura) sorta in risposta all'EC, rappresentando l'ossessione.",
        'ts1': "il tentativo (comportamentale o mentale) di neutralizzare o gestire la PV1 (ossessione), rappresentando la compulsione.",
        'sv2': "la valutazione critica o il giudizio (anche sulle conseguenze o costi) che il paziente fa sul primo ciclo (EC-PV1-TS1) o su sé stesso in relazione ad esso.",
        'ts2': "il tentativo (anche fallito) di contenere, modificare o evitare il ripetersi del primo ciclo (EC-PV1-TS1) in futuro (include tentativi di resistenza)."
    }
    role_description = definitions.get(component_key, "un elemento dello schema DOC")

    # Prompt v2: ancora più restrittivo sulla fedeltà e neutralità
    summarization_prompt = f"""CONTESTO: Stiamo costruendo uno schema di funzionamento DOC.
    COMPONENTE DA SINTETIZZARE: {component_key.upper()} - che rappresenta: {role_description}
    TESTO FORNITO DALL'UTENTE per questo componente: "{original_text_cleaned}"
    SCHEMA PARZIALE ATTUALE (per contesto addizionale): {schema_context}

    TASK: Rielabora il TESTO FORNITO DALL'UTENTE in una sintesi **estremamente concisa** (idealmente 1 frase breve, massimo 10-15 parole se possibile) per il componente {component_key.upper()}.
    **REGOLE FONDAMENTALI:**
    1.  **MASSIMA FEDELTÀ:** Usa **ESATTAMENTE le stesse parole chiave** dell'utente. Non sostituire parole se non strettamente necessario per la grammatica minima.
    2.  **NO INTERPRETAZIONE:** Non aggiungere **nessuna** interpretazione psicologica, giudizio o valutazione.
    3.  **NO PAROLE ESTERNE:** Non usare **mai** parole come 'errore', 'sbaglio', 'giusto', 'sbagliato', 'negativo', 'positivo', 'consapevolezza', 'impulso', 'tentativo', 'fallimento' a meno che non siano **presenti nel testo originale dell'utente**.
    4.  **CONCISIONE ESTREMA:** Rimuovi solo le parole superflue per rendere la frase più breve possibile mantenendo il significato letterale espresso dall'utente. Se il testo è già conciso, restituiscilo così com'è.

    Output Atteso: Solo la sintesi estremamente concisa e letterale.
    """
    try:
        summary = generate_response(
            prompt=summarization_prompt,
            history=[],
            model=st.session_state.get('model_gemini')
        )
        summary = summary.strip()

        error_indicators = [
            "risposta vuota dal modello", "bloccata per motivi di sicurezza",
            "non ho potuto elaborare", "errore tecnico imprevisto",
            "non riesco a riassumere", "non è possibile", "non chiaro",
            "necessarie ulteriori informazioni"
        ]

        is_valid_summary = True
        if not summary or len(summary) < 3: # Molto corto è sospetto
             is_valid_summary = False
             log_message(f"WARN: Sintesi per {component_key.upper()} troppo corta o vuota ('{summary}').")
        else:
            summary_lower = summary.lower()
            for indicator in error_indicators:
                if indicator in summary_lower:
                    is_valid_summary = False
                    log_message(f"WARN: Sintesi per {component_key.upper()} sembra un errore/blocco ('{summary}').")
                    break
            # Controllo aggiuntivo: se la sintesi è identica al testo originale lungo, potrebbe indicare fallimento
            if len(original_text_cleaned) > 30 and summary == original_text_cleaned:
                 log_message(f"WARN: Sintesi per {component_key.upper()} identica a originale lungo. Possibile fallimento LLM.")
                 # Potremmo decidere di usare comunque l'originale o tentare altro, per ora usiamo originale
                 is_valid_summary = False


        if not is_valid_summary:
             log_message(f"WARN: Usando testo originale per {component_key.upper()}.")
             return original_text_cleaned
        else:
            log_message(f"Sintesi fedele per {component_key.upper()}: '{summary}' (da: '{original_text_cleaned[:50]}...')")
            return summary.strip('"').strip("'")

    except Exception as e:
        log_message(f"ERRORE durante sintesi fedele per {component_key.upper()}: {e}. Uso testo originale.")
        return original_text_cleaned

# --- Funzioni Helper Riepilogo ---
# (Invariate, usano i valori sintetizzati/originali dallo schema)
def _create_summary_text(schema):
    ec = schema.get('ec', 'N/D')
    pv1 = schema.get('pv1', 'N/D')
    ts1 = schema.get('ts1', 'N/D')
    sv2 = schema.get('sv2')
    ts2 = schema.get('ts2')
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

def _create_first_part_summary_text(schema):
    ec = schema.get('ec', 'N/D')
    pv1 = schema.get('pv1', 'N/D')
    ts1 = schema.get('ts1')
    ts1_display = ts1 if ts1 else "(Compulsione non ancora identificata)"
    summary = f"""Ok, grazie. Dalla tua descrizione sembra che abbiamo identificato questa prima parte del ciclo:

* **Evento Critico (EC):** {ec}
* **Ossessione (PV1):** {pv1}
* **Compulsione (TS1):** {ts1_display}

Ti sembra che descriva correttamente l'inizio dell'esperienza? Possiamo andare avanti a esplorare cosa succede dopo (valutazioni e strategie future, che potrebbero esserci o meno)?
(Puoi dire 'sì' o indicare cosa modificare in questa prima parte)"""
    return summary

# --- Funzione Helper Pulizia JSON ---
# (Invariata)
def _clean_llm_json_response(llm_response_text):
    if not llm_response_text: return ""
    try:
        match = re.search(r"```json\s*(\{.*?\})\s*```", llm_response_text, re.DOTALL | re.IGNORECASE)
        if match: return match.group(1).strip()
        match = re.search(r"```\s*(\{.*?\})\s*```", llm_response_text, re.DOTALL)
        if match: return match.group(1).strip()
        stripped_response = llm_response_text.strip()
        if stripped_response.startswith('{') and stripped_response.endswith('}'):
             try: json.loads(stripped_response); return stripped_response
             except json.JSONDecodeError: pass
        log_message("WARN: Pulizia JSON non ha trovato ```json o ```. Uso testo grezzo.")
        return stripped_response
    except Exception as e:
        log_message(f"ERRORE in _clean_llm_json_response: {e}")
        return llm_response_text

# --- Funzione Helper Trova Mancante ---
# (Invariata)
def _find_next_missing_step(schema):
    if not isinstance(schema, dict):
        log_message("ERRORE CRITICO: _find_next_missing_step ha ricevuto uno schema non valido.")
        return 'ec'
    if not schema.get('ec'): return 'ec'
    if not schema.get('pv1'): return 'pv1'
    if not schema.get('ts1'): return 'ts1'
    if not schema.get('sv2'): return 'sv2'
    if not schema.get('ts2'): return 'ts2'
    return None

# --- Funzione Handler Principale ---
def handle(user_msg, current_state):
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

    # --- Logica Fasi Assessment ---

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
             log_message("Assessment Logic: Transizione ASSESSMENT_INTRO -> ASSESSMENT_GET_EXAMPLE.")
        else:
             new_state['phase'] = 'ASSESSMENT_GET_EXAMPLE'
             log_message("Assessment Logic: Input non conferma diretta, assumo sia inizio Esempio -> ASSESSMENT_GET_EXAMPLE.")

    elif current_phase == 'ASSESSMENT_GET_EXAMPLE':
        # (Logica estrazione e chiamata _summarize_component_clinically invariata)
        log_message(f"Assessment Logic: Ricevuto input in ASSESSMENT_GET_EXAMPLE: '{user_msg[:100]}...'")
        log_message("Assessment Logic: Avvio analisi LLM semplificata (EC, PV1, TS1)...")
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
        extracted_components = {'ec': None, 'pv1': None, 'ts1': None}
        llm_extraction_response = None
        parsing_ok = False
        try:
            llm_extraction_response = generate_response(prompt=extraction_prompt, history=[], model=st.session_state.get('model_gemini'))
            log_message(f"Assessment Logic: Risposta LLM grezza per estrazione semplificata: {llm_extraction_response}")
            if llm_extraction_response:
                clean_response = _clean_llm_json_response(llm_extraction_response)
                try:
                    parsed_data = json.loads(clean_response)
                    if isinstance(parsed_data, dict):
                        extracted_components['ec'] = parsed_data.get("ec") if parsed_data.get("ec") else None
                        extracted_components['pv1'] = parsed_data.get("pv1") if parsed_data.get("pv1") else None
                        extracted_components['ts1'] = parsed_data.get("ts1") if parsed_data.get("ts1") else None
                        log_message(f"Assessment Logic: Estrazione JSON semplificata riuscita - Dati RAW: {extracted_components}")
                        parsing_ok = True
                    else: log_message("Assessment Logic: WARN - Risposta LLM (sempl.) pulita non è un dizionario JSON valido.")
                except json.JSONDecodeError as json_err: log_message(f"Assessment Logic: ERRORE parsing JSON (sempl.) da LLM: {json_err}. Risposta LLM pulita: {clean_response}")
            else: log_message("Assessment Logic: WARN - Risposta LLM (sempl.) per estrazione è vuota.")
        except Exception as e: log_message(f"Assessment Logic: ERRORE durante chiamata LLM o processing (sempl.): {e}\n{traceback.format_exc()}")

        if not parsing_ok:
            log_message("Assessment Logic: Fallback (causa errore estrazione/parsing sempl.) - Uso l'intero user_msg come EC.")
            new_state['schema'] = INITIAL_STATE['schema'].copy()
            new_state['schema']['ec'] = user_msg # Salva testo grezzo
            new_state['phase'] = 'ASSESSMENT_GET_PV1'
            log_message(f"Assessment Logic: Transizione fallback a {new_state['phase']}.")
            ec_text = new_state['schema'].get('ec', 'la situazione descritta')
            llm_task_prompt = f"Grazie per aver descritto la situazione: '{ec_text[:100]}...'. Ora vorrei capire l'**Ossessione (PV1)**. Quale è stato il primo pensiero, immagine, dubbio o paura che hai avuto in *quel momento*?"
        else:
            # Successo: SINTETIZZA (fedelmente) e Salva EC, PV1, TS1 estratti
            for key, value in extracted_components.items():
                if value:
                    synthesized_value = _summarize_component_clinically(key, value, new_state['schema'])
                    new_state['schema'][key] = synthesized_value
                else:
                     new_state['schema'][key] = None
            log_message(f"Assessment Logic: Schema aggiornato dopo estrazione e SINTESI FEDELE: {new_state['schema']}")
            new_state['phase'] = 'ASSESSMENT_CONFIRM_FIRST_PART'
            log_message(f"Assessment Logic: Transizione a {new_state['phase']}.")
            bot_response_text = _create_first_part_summary_text(new_state['schema'])

    elif current_phase == 'ASSESSMENT_CONFIRM_FIRST_PART':
        # (Logica invariata)
        log_message(f"Assessment Logic: Gestione fase '{current_phase}'")
        user_msg_processed = user_msg.strip().lower()
        is_modification_request = any(keyword in user_msg_processed for keyword in ["modifi", "cambia", "aggiust", "corregg", "rivedere", "precisare", "sbagliato", "errato", "non è", "diverso"]) or \
                                  any(word in negazioni_o_dubbi for word in user_msg_processed.split() if word not in ['non'])
        is_confirmation = (user_msg_processed in conferme or \
                          any(user_msg_processed.startswith(conf + " ") for conf in conferme if isinstance(conf, str)) or \
                          any(word in conferme for word in user_msg_processed.split())) \
                          and not is_modification_request
        if is_confirmation:
            log_message("Assessment Logic: Prima parte (EC/PV1/TS1) confermata.")
            new_state['phase'] = 'ASSESSMENT_GET_SV2'
            log_message(f"Assessment Logic: Transizione a {new_state['phase']}.")
            pv1_text = new_state['schema'].get('pv1', '...')
            ts1_text = new_state['schema'].get('ts1', '...')
            llm_task_prompt = f"Perfetto, grazie. Ora esploriamo cosa succede dopo la Compulsione ('{ts1_text[:80]}...'). A volte, ci sono altri pensieri o valutazioni (Seconda Valutazione - SV2), e magari strategie per evitare il problema in futuro (Tentativo Soluzione 2 - TS2). Questi elementi non sono sempre presenti o evidenti. \n\nConcentriamoci sulla **Seconda Valutazione (SV2)**: subito **dopo** l'Ossessione ('{pv1_text[:80]}...') o la Compulsione ('{ts1_text[:80]}...'), cosa hai **PENSATO** o **GIUDICATO** riguardo a quello che stava succedendo, all'ossessione stessa, alla compulsione o alle sue conseguenze? (Non solo l'emozione)."
        elif is_modification_request:
            log_message("Assessment Logic: Richiesta modifica prima parte.")
            new_state['originating_confirmation_phase'] = 'ASSESSMENT_CONFIRM_FIRST_PART'
            new_state['phase'] = 'ASSESSMENT_AWAIT_EDIT_TARGET'
            log_message(f"Assessment Logic: Transizione a {new_state['phase']} (da {current_phase}).")
            bot_response_text = "Certamente. Quale parte specifica di questa prima fase (Evento Critico, Ossessione, Compulsione) vuoi modificare o precisare?"
        else:
            log_message("Assessment Logic: Risposta non chiara a conferma prima parte. Richiedo.")
            new_state['phase'] = 'ASSESSMENT_CONFIRM_FIRST_PART'
            summary_text_only = _create_first_part_summary_text(new_state['schema']).split("* **Evento Critico (EC):**")[1]
            bot_response_text = f"Scusa, non ho afferrato bene. Riguardando questa prima parte:\n\n* **Evento Critico (EC):**{summary_text_only}"

    elif current_phase == 'ASSESSMENT_GET_PV1':
        # (Logica invariata, usa _summarize_component_clinically)
        log_message(f"Assessment Logic: Ricevuto input esplicito per PV1: {user_msg[:50]}...")
        synthesized_pv1 = _summarize_component_clinically('pv1', user_msg, new_state['schema'])
        new_state['schema']['pv1'] = synthesized_pv1
        next_missing = _find_next_missing_step(new_state['schema'])
        if next_missing == 'ts1':
             new_state['phase'] = 'ASSESSMENT_GET_TS1'
             log_message(f"Assessment Logic: PV1 sintetizzato e salvato. Prossimo mancante '{next_missing}'. Transizione a {new_state['phase']}.")
             pv1_text = new_state['schema'].get('pv1', '...')
             llm_task_prompt = f"Ok, l'Ossessione (PV1) è '{pv1_text[:100]}...'. Adesso passiamo alla **Compulsione (TS1)**. Cosa hai fatto/pensato/sentito *in risposta diretta*?"
        else:
            new_state['phase'] = 'ASSESSMENT_CONFIRM_FIRST_PART'
            log_message(f"Assessment Logic: PV1 sintetizzato e salvato. TS1 già presente. Transizione a {new_state['phase']}.")
            bot_response_text = _create_first_part_summary_text(new_state['schema'])

    elif current_phase == 'ASSESSMENT_GET_TS1':
        # (Logica invariata, usa _summarize_component_clinically)
        log_message(f"Assessment Logic: Ricevuto input esplicito per TS1: {user_msg[:50]}...")
        synthesized_ts1 = _summarize_component_clinically('ts1', user_msg, new_state['schema'])
        new_state['schema']['ts1'] = synthesized_ts1
        new_state['phase'] = 'ASSESSMENT_CONFIRM_FIRST_PART'
        log_message(f"Assessment Logic: TS1 sintetizzato e salvato. Transizione a {new_state['phase']}.")
        bot_response_text = _create_first_part_summary_text(new_state['schema'])

    elif current_phase == 'ASSESSMENT_GET_SV2':
        # (Logica validazione con prompt affinato e chiamata _summarize_component_clinically invariata)
        log_message(f"Assessment Logic: Ricevuto input per SV2: {user_msg[:50]}...")
        sv2_input = user_msg.strip()
        if sv2_input.lower() in negazioni_esplicite:
            log_message("Assessment Logic: SV2 interpretato come non significativo (negazione esplicita).")
            new_state['schema']['sv2'] = None
            new_state['phase'] = 'ASSESSMENT_GET_TS2'
            log_message("Assessment Logic: Transizione a ASSESSMENT_GET_TS2.")
            llm_task_prompt = f"Capito (SV2 non significativa). Ora l'ultimo punto: il **Tentativo di Soluzione 2 (TS2)**. C'è stata qualche strategia/intenzione futura per **evitare situazioni simili**, **prevenire l'ossessione**, o **gestire diversamente la compulsione**? Hai provato a resistere?"
        else:
            log_message("Assessment Logic: Avvio validazione LLM per SV2...")
            # Prompt validazione v2: più chiaro su conseguenze
            validation_prompt = f"""ANALISI RISPOSTA UTENTE PER SECONDA VALUTAZIONE (SV2)
            CONTESTO: Dopo Evento Critico (EC)="{new_state['schema'].get('ec', 'N/D')}", Ossessione (PV1)="{new_state['schema'].get('pv1', 'N/D')}", e Compulsione (TS1)="{new_state['schema'].get('ts1', 'N/D')}".
            DOMANDA POSTA ALL'UTENTE: Chiedeva la Seconda Valutazione (SV2) - il PENSIERO o GIUDIZIO (anche su conseguenze) dopo PV1/TS1, non solo l'emozione.
            RISPOSTA UTENTE DA ANALIZZARE: "{sv2_input}"
            TASK: La risposta dell'utente descrive effettivamente una Valutazione Cognitiva Secondaria (SV2)?
            - È un pensiero, un giudizio, una valutazione (anche metacognitiva), una riflessione sulle **conseguenze** (es. "rischierò il licenziamento", "farò tardi", "ho pensato che fosse terribile", "questo pensiero è inaccettabile")? -> VALIDO_SV2
            - È SOLO un'emozione (es. "ansia", "paura")? -> NON_VALIDO_SV2
            - È un'azione, un comportamento, un tentativo (anche fallito) di fare/non fare qualcosa (es. "sono tornato indietro", "ho cercato di resistere", "ho chiesto rassicurazioni")? -> NON_VALIDO_SV2
            - È una negazione esplicita o "non lo so"? -> NEGATIVO
            - È qualcos'altro di non pertinente? -> NON_VALIDO_SV2
            Output Atteso: Rispondi ESATTAMENTE con UNA delle seguenti stringhe: VALIDO_SV2, NON_VALIDO_SV2, NEGATIVO
            """
            try:
                validation_response = generate_response(prompt=validation_prompt, history=[], model=st.session_state.get('model_gemini')).strip().upper()
                log_message(f"Assessment Logic: Risultato validazione LLM per SV2: '{validation_response}'")

                if validation_response == 'VALIDO_SV2':
                    log_message("Assessment Logic: SV2 validato come VALIDO.")
                    synthesized_sv2 = _summarize_component_clinically('sv2', sv2_input, new_state['schema'])
                    new_state['schema']['sv2'] = synthesized_sv2
                    new_state['phase'] = 'ASSESSMENT_GET_TS2'
                    log_message("Assessment Logic: Transizione a ASSESSMENT_GET_TS2.")
                    sv2_text = new_state['schema'].get('sv2', 'la valutazione precedente')
                    llm_task_prompt = f"Capito (SV2: {sv2_text[:80]}...). Ora l'ultimo punto: il **Tentativo di Soluzione 2 (TS2)**. C'è stata qualche strategia/intenzione futura per **evitare situazioni simili**, **prevenire l'ossessione**, o **gestire diversamente la compulsione**? Hai provato a resistere?"
                elif validation_response == 'NEGATIVO':
                    log_message("Assessment Logic: SV2 validato come NEGATIVO.")
                    new_state['schema']['sv2'] = None
                    new_state['phase'] = 'ASSESSMENT_GET_TS2'
                    log_message("Assessment Logic: Transizione a ASSESSMENT_GET_TS2.")
                    llm_task_prompt = f"Capito (SV2 non significativa). Ora l'ultimo punto: il **Tentativo di Soluzione 2 (TS2)**. C'è stata qualche strategia/intenzione futura per **evitare situazioni simili**, **prevenire l'ossessione**, o **gestire diversamente la compulsione**? Hai provato a resistere?"
                else: # NON_VALIDO_SV2 o altro
                    log_message("Assessment Logic: SV2 validato come NON VALIDO. Richiedo.")
                    new_state['phase'] = 'ASSESSMENT_GET_SV2'
                    pv1_text = new_state['schema'].get('pv1', '...')
                    ts1_text = new_state['schema'].get('ts1', '...')
                    llm_task_prompt = f"Ok, grazie per la risposta ('{sv2_input[:80]}...'). Tuttavia, stiamo cercando specificamente la **Seconda Valutazione (SV2)**: un **pensiero**, un **giudizio** o una **valutazione** (anche sulle conseguenze, come 'rischierò il licenziamento') che hai avuto *dopo* l'ossessione ('{pv1_text[:80]}...') o la compulsione ('{ts1_text[:80]}...'). Non l'emozione o l'azione stessa. C'è stato un pensiero o giudizio specifico in quel momento? (Se non c'è stato o non ricordi, dimmi pure 'nessuno' o 'non ricordo')."
            except Exception as e:
                log_message(f"ERRORE durante validazione LLM per SV2: {e}. Richiedo.")
                new_state['phase'] = 'ASSESSMENT_GET_SV2'
                llm_task_prompt = f"Scusa, ho avuto un problema nell'analizzare la tua risposta per la Seconda Valutazione. Potresti ripeterla o riformularla? Ricorda, cerchiamo un pensiero o un giudizio avuto dopo l'ossessione o la compulsione."

    elif current_phase == 'ASSESSMENT_GET_TS2':
        # (Logica invariata, usa _summarize_component_clinically)
        log_message(f"Assessment Logic: Ricevuto input esplicito per TS2: {user_msg[:50]}...")
        ts2_value = user_msg.strip()
        if ts2_value.lower() in negazioni_esplicite:
             new_state['schema']['ts2'] = None
             log_message("Assessment Logic: TS2 interpretato come non significativo.")
        else:
             synthesized_ts2 = _summarize_component_clinically('ts2', ts2_value, new_state['schema'])
             new_state['schema']['ts2'] = synthesized_ts2
             log_message("Assessment Logic: TS2 sintetizzato e salvato.")
        new_state['phase'] = 'ASSESSMENT_CONFIRM_SCHEMA'
        bot_response_text = _create_summary_text(new_state['schema'])
        log_message("Assessment Logic: Transizione a ASSESSMENT_CONFIRM_SCHEMA.")

    elif current_phase == 'ASSESSMENT_CONFIRM_SCHEMA':
        # (Logica invariata)
        log_message(f"Assessment Logic: Gestione fase '{current_phase}'")
        user_msg_processed = user_msg.strip().lower()
        is_modification_request = any(keyword in user_msg_processed for keyword in ["modifi", "cambia", "aggiust", "corregg", "rivedere", "precisare", "sbagliato", "errato", "non è", "diverso"]) or \
                                  any(word in negazioni_o_dubbi for word in user_msg_processed.split() if word not in ['non'])
        is_confirmation = (user_msg_processed in conferme or \
                          any(user_msg_processed.startswith(conf + " ") for conf in conferme if isinstance(conf, str)) or \
                          any(word in conferme for word in user_msg_processed.split())) \
                          and not is_modification_request
        if is_confirmation:
            new_state['phase'] = 'RESTRUCTURING_INTRO'
            bot_response_text = "Ottimo, grazie per la conferma! Avere chiaro questo schema completo è un passo importante.\n\nOra che abbiamo definito un esempio del ciclo, possiamo iniziare ad approfondire le valutazioni e i pensieri che lo mantengono. Ti andrebbe di passare alla fase successiva, chiamata **Ristrutturazione Cognitiva**?"
            log_message(f"Assessment Logic: Schema COMPLETO confermato. Transizione proposta a RESTRUCTURING_INTRO.")
        elif is_modification_request:
            new_state['originating_confirmation_phase'] = 'ASSESSMENT_CONFIRM_SCHEMA'
            new_state['phase'] = 'ASSESSMENT_AWAIT_EDIT_TARGET'
            log_message(f"Assessment Logic: Richiesta modifica schema completo. Transizione a {new_state['phase']}.")
            bot_response_text = "Certamente. Quale parte specifica dello schema completo (Evento Critico, Ossessione, Compulsione, Seconda Valutazione, Tentativo Soluzione 2) vuoi modificare o precisare?"
        else:
            log_message("Assessment Logic: Risposta non chiara a conferma schema completo. Richiedo.")
            summary_part = _create_summary_text(new_state['schema'])
            bot_response_text = f"Scusa, non ho capito bene. Ricontrolliamo lo schema completo:\n\n{summary_part}\n\nVa bene così com'è? Dimmi 'sì' se è corretto, oppure indica quale parte vuoi cambiare."
            new_state['phase'] = 'ASSESSMENT_CONFIRM_SCHEMA'

    elif current_phase == 'ASSESSMENT_AWAIT_EDIT_TARGET':
        # (Logica invariata)
         log_message(f"Assessment Logic: Gestione fase '{current_phase}'")
         user_input_lower = user_msg.lower()
         target_key = None
         if 'seconda valutazione' in user_input_lower or 'sv2' in user_input_lower: target_key = 'sv2'
         elif 'tentativo' in user_input_lower or 'ts2' in user_input_lower or 'soluzione 2' in user_input_lower or 'evitamento ciclo' in user_input_lower : target_key = 'ts2'
         elif 'compulsione' in user_input_lower or 'ts1' in user_input_lower: target_key = 'ts1'
         elif 'ossessione' in user_input_lower or 'pv1' in user_input_lower or 'prima valutazione' in user_input_lower : target_key = 'pv1'
         elif 'evento' in user_input_lower or 'critico' in user_input_lower or 'ec' in user_input_lower or 'situazione' in user_input_lower: target_key = 'ec'
         origin_phase = current_state.get('originating_confirmation_phase', 'ASSESSMENT_CONFIRM_SCHEMA')
         allowed_targets = ['ec', 'pv1', 'ts1'] if origin_phase == 'ASSESSMENT_CONFIRM_FIRST_PART' else ['ec', 'pv1', 'ts1', 'sv2', 'ts2']
         if target_key and target_key in allowed_targets:
             new_state['editing_target'] = target_key
             new_state['phase'] = f'ASSESSMENT_EDIT_{target_key.upper()}'
             target_names = {'ec': 'Evento Critico', 'pv1': 'Ossessione', 'ts1': 'Compulsione', 'sv2': 'Seconda Valutazione', 'ts2': 'Tentativo Soluzione 2'}
             target_name = target_names.get(target_key, target_key)
             current_value = new_state.get('schema', {}).get(target_key, "Non definito")
             llm_task_prompt = f"Ok, vuoi modificare '{target_name}'. Il valore attuale (sintetizzato) è: \"{current_value}\". Per favore, fornisci la nuova descrizione completa per questo punto (verrà risintetizzata)."
             log_message(f"Assessment Logic: Target modifica '{target_key}'. Transizione a {new_state['phase']}.")
         else:
             allowed_targets_text = ", ".join([t.upper() for t in allowed_targets])
             bot_response_text = f"Non ho capito bene quale punto vuoi modificare o non è possibile modificare quel punto ora. Puoi indicarmi uno tra: {allowed_targets_text}?"
             new_state['phase'] = 'ASSESSMENT_AWAIT_EDIT_TARGET'
             log_message(f"Assessment Logic: Target modifica '{target_key}' non identificato o non permesso da {origin_phase}. Richiedo.")

    elif current_phase.startswith('ASSESSMENT_EDIT_'):
        # (Logica invariata, usa _summarize_component_clinically)
        target_key = current_state.get('editing_target')
        schema_dict = new_state.get('schema')
        origin_phase = current_state.get('originating_confirmation_phase', 'ASSESSMENT_CONFIRM_SCHEMA')
        if target_key and isinstance(schema_dict, dict) and target_key in schema_dict:
             log_message(f"Assessment Logic: Ricevuto nuovo valore per {target_key}: {user_msg[:50]}...")
             new_value = user_msg.strip()
             if target_key in ['sv2', 'ts2'] and new_value.lower() in negazioni_esplicite:
                 synthesized_value = None
                 log_message(f"Assessment Logic: Valore per {target_key} impostato a None durante modifica.")
             else:
                 synthesized_value = _summarize_component_clinically(target_key, new_value, schema_dict)
             schema_dict[target_key] = synthesized_value
             new_state['phase'] = origin_phase
             if origin_phase == 'ASSESSMENT_CONFIRM_FIRST_PART':
                 bot_response_text = _create_first_part_summary_text(schema_dict)
             else:
                 bot_response_text = _create_summary_text(schema_dict)
             log_message(f"Assessment Logic: Valore '{target_key}' aggiornato (e sintetizzato). Ritorno a {origin_phase}.")
        else:
             log_message(f"Assessment Logic: ERRORE CRITICO in EDIT - editing_target '{target_key}' non valido/trovato o schema non è dict. Schema: {schema_dict}. Ripristino.")
             new_state = current_state.copy()
             new_state['phase'] = origin_phase
             if 'editing_target' in new_state: del new_state['editing_target']
             if 'originating_confirmation_phase' in new_state: del new_state['originating_confirmation_phase']
             if origin_phase == 'ASSESSMENT_CONFIRM_FIRST_PART':
                 bot_response_text = "Scusa, problema tecnico nella modifica. Rivediamo la prima parte:\n\n" + _create_first_part_summary_text(new_state.get('schema', {})).split("Ok, grazie. ")[1]
             else:
                 bot_response_text = "Scusa, problema tecnico nella modifica. Rivediamo lo schema completo:\n\n" + _create_summary_text(new_state.get('schema', {}))
        if 'editing_target' in new_state: del new_state['editing_target']
        if 'originating_confirmation_phase' in new_state: del new_state['originating_confirmation_phase']

    elif current_phase == 'ASSESSMENT_COMPLETE': # Obsoleto
        # (Logica invariata)
        log_message("Assessment Logic: WARN - Raggiunta fase ASSESSMENT_COMPLETE (obsoleta). Reindirizzo a RESTRUCTURING_INTRO.")
        new_state['phase'] = 'RESTRUCTURING_INTRO'
        bot_response_text = "Abbiamo completato la valutazione dell'esempio. Ti andrebbe ora di passare alla fase successiva, la **Ristrutturazione Cognitiva**?"

    # --- Gestione Chiamata LLM Specifica ---
    if llm_task_prompt:
        # (Logica invariata)
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
ISTRUZIONI: Rispondi in ITALIANO. Tono empatico, chiaro, CONCISO. Fai UNA domanda alla volta. Non usare sigle (EC, PV1 ecc.) nella domanda diretta all'utente, usa i nomi completi (es. Evento Critico). Non chiedere informazioni già presenti nello SCHEMA UTENTE PARZIALE.
OBIETTIVO SPECIFICO: {llm_task_prompt}"""
        bot_response_text = generate_response(prompt=f"{system_prompt}\n\n---\n\nUltimo Messaggio Utente (da ignorare se il prompt lo include già): {user_msg}", history=chat_history_for_llm, model=st.session_state.get('model_gemini'))

    # --- Fallback Generico ---
    elif not bot_response_text:
        # (Logica invariata)
        log_message(f"Assessment Logic: Nessuna logica specifica o task LLM per fase '{current_phase}'. Eseguo fallback generico...")
        rag_context = ""
        system_prompt_generic = f"""Sei un assistente empatico per il supporto al DOC (TCC). FASE CONVERSAZIONE ATTUALE: {new_state['phase']}. SCHEMA UTENTE: {new_state.get('schema', {})}.{rag_context} ISTRUZIONI: Rispondi in ITALIANO. Tono empatico, chiaro, CONCISO. L'utente ha inviato un messaggio ('{user_msg[:100]}...') che non rientra nel flusso previsto. Rispondi in modo utile e pertinente. Guida gentilmente verso l'obiettivo della fase attuale ({current_phase}). Fai UNA domanda alla volta se necessario."""
        chat_history_for_llm = []
        bot_response_text = generate_response(prompt=f"{system_prompt_generic}", history=chat_history_for_llm, model=st.session_state.get('model_gemini'))
        log_message("Assessment Logic: Eseguito LLM generico di fallback.")

    # Fallback finale
    if not bot_response_text:
        log_message("Assessment Logic: WARN - bot_response_text ancora vuoto. Risposta fallback finale.")
        bot_response_text = "Non sono sicuro di come continuare da qui. Potresti riformulare?"

    # Pulisci stati temporanei
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
