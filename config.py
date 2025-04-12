# config.py (Struttura Modulare a Fasi)
# Contiene costanti, configurazioni modelli, prompt iniziali,
# stato iniziale e la mappa FASE -> CHIAVE_RAG.

# --- Modelli AI ---
EMBEDDING_MODEL_NAME = "models/text-embedding-004"
GENERATION_MODEL_NAME = "models/gemini-1.5-flash-latest" # O "models/gemini-1.5-pro-latest"

SAFETY_SETTINGS_GEMINI = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
]
GENERATION_CONFIG_GEMINI = {
    "temperature": 0.7,
    "top_p": 0.95,
    "top_k": 40,
    "max_output_tokens": 2048,
    "candidate_count": 1
}

# --- Costanti Chat ---
INTRO_MESSAGE = """Ciao! Sono un assistente conversazionale per supportarti nella gestione del Disturbo Ossessivo-Compulsivo (DOC), basandomi su principi e tecniche di terapia cognitivo-comportamentale (TCC).

Il nostro percorso insieme si strutturerà indicativamente così:
1.  **Valutazione:** Inizieremo con un esempio concreto per capire meglio come funziona il DOC per te e ricostruiremo insieme lo schema di funzionamento (Evento Critico, Ossessione, Compulsione, Valutazioni).
2.  **Ristrutturazione Cognitiva:** Esploreremo i pensieri e le valutazioni che alimentano il ciclo del DOC.
3.  **Esposizione e Prevenzione della Risposta (ERP):** Impareremo tecniche pratiche per affrontare le paure e ridurre le compulsioni.
4.  **Accettazione e Valori (ACT):** Vedremo come gestire i pensieri difficili e vivere secondo ciò che più conta per te.
5.  **Gestione della Vulnerabilità e Ricadute:** Impareremo a riconoscere e gestire i momenti di difficoltà.

**Nota Importante:** Questo strumento è stato realizzato dal Dott. Ivan Pavesi come supporto psicoeducativo e NON sostituisce un terapeuta umano qualificato. Il tuo feedback è prezioso per migliorarlo (ivanpavesi@gmail.com). Grazie!

Sei pronto/a per iniziare questo percorso insieme? (Puoi rispondere 'sì', 'ok' o iniziare a raccontare un esempio)"""

# Stato iniziale della conversazione
INITIAL_STATE = {
    'phase': 'START', # La fase iniziale gestita da assessment_logic.py
    'schema': { 'ec': None, 'pv1': None, 'ts1': None, 'sv2': None, 'ts2': None }
    # Aggiungere qui altri campi di stato se servono globalmente o per fasi future
}

# Liste per risposte comuni
CONFERME = ['sì', 'si', 'ok', 'va bene', 'certo', 'yes', 'yep', 'volentieri', 'procediamo', 'iniziamo', 'sono pronto', 'pronto', 'd\'accordo', 'esatto', 'giusto', 'confermo']
NEGAZIONI_O_DUBBI = ['no', 'non', 'non sono sicuro', 'aspetta', 'non ho capito', 'perché', 'non lo so', 'non ricordo', 'non credo', 'sbagliato', 'errato', 'diverso', 'cambia', 'modifica']

# --- MAPPATURA FASE LOGICA -> CHIAVE STEP RAG ---
# Collega il nome della fase logica (usato in state_manager e nei moduli delle fasi)
# alla chiave corrispondente per la ricerca RAG specifica per step.
# Le chiavi RAG (a destra) devono corrispondere ai nomi dei file indice/mappa
# (es. 'step_1_descrizione_doc.index', 'step_1_descrizione_doc.pkl').

# Chiavi STEP RAG disponibili (basate sul workbook_estratto.txt):
# 'step_1_descrizione_doc', 'step_2_schema_funzionamento_doc', 'step_3_intervento_secondo_processo_ricorsivo',
# 'step_4_intervento_primo_processo_ricorsivo', 'step_5_esposizione_ERP', 'step_6_anti_disgusto',
# 'step_7_ACT', 'step_8_intervento_terzo_processo_ricorsivo_famiglia', 'step_9_prevenire_ricadute'

PHASE_TO_CHAPTER_KEY_MAP = {
    # --- Fasi di Assessment (Capitolo 2) ---
    # Tutte le fasi gestite da assessment_logic.py usano il contesto del capitolo 2
    'START':                     'step_2_schema_funzionamento_doc',
    'ASSESSMENT_INTRO':          'step_2_schema_funzionamento_doc',
    'ASSESSMENT_GET_EXAMPLE':    'step_2_schema_funzionamento_doc',
    'ASSESSMENT_GET_PV1':        'step_2_schema_funzionamento_doc',
    'ASSESSMENT_GET_TS1':        'step_2_schema_funzionamento_doc',
    'ASSESSMENT_GET_SV2':        'step_2_schema_funzionamento_doc',
    'ASSESSMENT_GET_TS2':        'step_2_schema_funzionamento_doc',
    'ASSESSMENT_CONFIRM_SCHEMA': 'step_2_schema_funzionamento_doc',
    'ASSESSMENT_AWAIT_EDIT_TARGET': 'step_2_schema_funzionamento_doc',
    'ASSESSMENT_EDIT_EC':        'step_2_schema_funzionamento_doc',
    'ASSESSMENT_EDIT_PV1':       'step_2_schema_funzionamento_doc',
    'ASSESSMENT_EDIT_TS1':       'step_2_schema_funzionamento_doc',
    'ASSESSMENT_EDIT_SV2':       'step_2_schema_funzionamento_doc',
    'ASSESSMENT_EDIT_TS2':       'step_2_schema_funzionamento_doc',
    'ASSESSMENT_COMPLETE':       'step_2_schema_funzionamento_doc', # Utile per riassumere/transitare

    # --- Fasi di Ristrutturazione Cognitiva (Capitolo 3 - Processo 2) ---
    # Assicurati che questi nomi fase siano usati in restructuring_logic.py
    'RESTRUCTURING_INTRO':       'step_3_intervento_secondo_processo_ricorsivo',
    'RESTRUCTURING_IDENTIFY_HOT': 'step_3_intervento_secondo_processo_ricorsivo',
    # ... altre fasi di ristrutturazione ...

    # --- Fasi ERP (Capitolo 5) ---
    # Assicurati che questi nomi fase siano usati in erp_logic.py
    'ERP_INTRO':                 'step_5_esposizione_ERP',
    'ERP_BUILD_HIERARCHY':       'step_5_esposizione_ERP',
    # ... altre fasi ERP ...

    # --- Fasi ACT (Capitolo 7) ---
    # Assicurati che questi nomi fase siano usati in act_logic.py
    'ACT_VALUES_INTRO':          'step_7_ACT',
    'ACT_DEFUSION_INTRO':        'step_7_ACT',
    # ... altre fasi ACT ...

    # --- Fasi Anti-Disgusto (Capitolo 6) ---
     'DISGUST_INTRO':             'step_6_anti_disgusto',
     # ... altre fasi disgusto ...

     # --- Fasi Prevenzione Ricadute (Capitolo 9) ---
     'RELAPSE_INTRO':             'step_9_prevenire_ricadute',
     # ... altre fasi ricadute ...

    # Aggiungi qui altre mappature per nuove fasi implementate
}
# --------------------------------------------------------------------

