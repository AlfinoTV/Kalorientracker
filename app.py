import streamlit as st
import google.generativeai as genai
from supabase import create_client, Client
from PIL import Image
import json
import io
import base64
from datetime import datetime, date

# ==========================================
# 1. KONFIGURATION & ZUGANGSDATEN
# ==========================================
st.set_page_config(page_title="Kalorien Tracker", page_icon="🍏", layout="centered")

GOOGLE_API_KEY = "AQ.Ab8RN6Ifi6Pi8Jr6rJ38oVTRzWstHGuH40QXcJo04rGX5d8RMQ"
SUPABASE_URL = "https://jqywogdgttgcvrzltgit.supabase.co"
SUPABASE_KEY = "sb_publishable_HIxDWl3-q_BB2wtSD2a-Uw_z6HeO8Be"

genai.configure(api_key=GOOGLE_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# 2. DATENBANK-FUNKTIONEN
# ==========================================
def get_tagesziel():
    try:
        res = supabase.table("einstellungen").select("tagesziel").execute()
        return res.data[0]["tagesziel"] if res.data else 2000
    except:
        return 2000

def update_tagesziel(neu_ziel):
    try:
        supabase.table("einstellungen").upsert({"id": 1, "tagesziel": neu_ziel}).execute()
    except Exception as e:
        st.error(f"Fehler beim Speichern des Tagesziels: {e}")

def get_mahlzeiten():
    try:
        res = supabase.table("mahlzeiten").select("*").order("created_at", desc=True).execute()
        return res.data if res.data else []
    except Exception as e:
        # Falls die Datenbank zickt, stürzt nicht die ganze App ab!
        st.sidebar.error(f"Datenbank-Fehler: {e}")
        return []

def add_mahlzeit(gericht, kalorien, bild_base64=""):
    supabase.table("mahlzeiten").insert({
        "gericht": gericht, 
        "kalorien": kalorien, 
        "bild_data": bild_base64
    }).execute()

def update_mahlzeit(id, neu_gericht, neu_kalorien):
    supabase.table("mahlzeiten").update({
        "gericht": neu_gericht, 
        "kalorien": neu_kalorien
    }).eq("id", id).execute()

def delete_mahlzeit(id):
    supabase.table("mahlzeiten").delete().eq("id", id).execute()

# ==========================================
# 3. DATEN LADEN & SORTIEREN
# ==========================================
aktuelles_ziel = get_tagesziel()
alle_mahlzeiten = get_mahlzeiten()

heute_str = date.today().isoformat()
heutige_mahlzeiten = []
historie = {}

for item in alle_mahlzeiten:
    eintrag_datum = item["created_at"].split("T")[0]
    if eintrag_datum == heute_str:
        heutige_mahlzeiten.append(item)
    else:
        if eintrag_datum not in historie:
            historie[eintrag_datum] = []
        historie[eintrag_datum].append(item)

# ==========================================
# 4. DASHBOARD (DIE BILANZ)
# ==========================================
st.title("🍏 Unser Kalorien-Tracker")
st.caption("Gemeinsam fit – Daten werden live in der Cloud gespeichert.")

st.subheader("📊 Heutige Bilanz")

with st.form("ziel_form", clear_on_submit=False):
    tagesziel = st.number_input("Dein Tagesziel (kcal)", value=int(aktuelles_ziel), step=50)
    speichern_btn = st.form_submit_button("🎯 Ziel aktualisieren")
    if speichern_btn:
        update_tagesziel(tagesziel)
        st.success("Tagesziel wurde gespeichert!")
        st.rerun()

gesamte_kalorien = sum(item['kalorien'] for item in heutige_mahlzeiten)
restkalorien = tagesziel - gesamte_kalorien

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("🎯 Ziel", f"{tagesziel} kcal")
with col2:
    st.metric("🍳 Gegessen", f"{gesamte_kalorien} kcal")
with col3:
    st.metric("🔑 Restlich", f"{restkalorien} kcal", delta=f"{-gesamte_kalorien} kcal")

fortschritt = min(gesamte_kalorien / tagesziel, 1.0) if tagesziel > 0 else 0.0
st.progress(fortschritt)

st.divider()

# ==========================================
# 5. KI MULTI-UPLOAD ODER TEXT-INPUT TRACKER (KOMPRIMIERT)
# ==========================================
st.subheader("📸 Mahlzeit tracken")

if "file_uploader_key" not in st.session_state:
    st.session_state["file_uploader_key"] = 0

# 1. Option: Klassischer Bilder-Upload
uploaded_files = st.file_uploader(
    "Wähle Bilder deiner Zutaten aus (z.B. Brot, Soße, Käse)...", 
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
    key=f"uploader_{st.session_state['file_uploader_key']}"
)

if uploaded_files:
    cols = st.columns(len(uploaded_files))
    for idx, file in enumerate(uploaded_files):
        with cols[idx]:
            img = Image.open(file)
            st.image(img, caption=f"Zutat {idx+1}", use_container_width=True)

# 2. Option: TEXTFELD (Mit dynamischem Key zum automatischen Leeren)
text_mahlzeit = st.text_input(
    "✍️ Oder tippe hier ein, was du gegessen hast:", 
    placeholder="z.B. Ein halber Döner mit Knoblauchsoße oder 250g Quark mit Banane...",
    key=f"text_input_{st.session_state['file_uploader_key']}"
)

# Zusatzinfos für Bilder
zusatz_info = st.text_input("💡 Zusatzinfos zu den Zutaten (nur für Bild-Upload wichtig):", placeholder="z.B. 2 Scheiben Brot, 1 EL Soße, 2 Scheiben Käse...")

# Analyse-Button
if st.button("🚀 Mahlzeit analysieren & speichern", use_container_width=True):
    if not uploaded_files and not text_mahlzeit.strip():
        st.warning("Bitte lade entweder ein Bild hoch ODER tippe im Textfeld ein, was du gegessen hast! 😉")
    else:
        with st.spinner("KI berechnet deine Mahlzeit mit der Kalorienbremse..."):
            try:
                ai_contents = []
                bilder_string_fuer_db = ""
                
                # --- WEG A: Es wurden BILDER hochgeladen ---
                if uploaded_files:
                    alle_bilder_base64 = []
                    for file in uploaded_files:
                        image = Image.open(file)
                        if image.mode in ("RGBA", "P"):
                            image = image.convert("RGB")
                        elif image.mode != "RGB":
                            image = image.convert("RGB")
                            
                        # --- NEU: BILD GRÖSSE REDUZIEREN (Komprimierung für Supabase) ---
                        # Wir begrenzen die maximale Breite/Höhe auf 500 Pixel für die DB-Schonung
                        image.thumbnail((500, 500))
                        
                        img_byte_arr = io.BytesIO()
                        # Qualität auf 60% senken (reicht für die Vorschau völlig aus und spart 90% Speicher)
                        image.save(img_byte_arr, format='JPEG', quality=60)
                        img_bytes = img_byte_arr.getvalue()
                        
                        b64_str = base64.b64encode(img_bytes).decode('utf-8')
                        alle_bilder_base64.append(b64_str)
                        
                        # Für Google Gemini nutzen wir das komprimierte Byte-Array
                        ai_contents.append({
                            "mime_type": "image/jpeg",
                            "data": img_bytes
                        })
                    bilder_string_fuer_db = ",".join(alle_bilder_base64)
                    
                    prompt = f"""Du bist ein professioneller Ernährungsberater und Kalorien-Experte.
Die beigefügten Bilder zeigen die einzelnen ZUTATEN (Anzahl: {len(uploaded_files)}) für EINE EINZIGE gemeinsame Mahlzeit.

Kritische Nutzer-Zusatzinfo: "{zusatz_info}"

⚠️ STRENGE REGELN FÜR DIE SCHÄTZUNG:
1. Schätze die Kalorien für jede Zutat einzeln und addiere sie zu einem Gesamtwert für die MAHLZEIT.
2. Tracke extrem streng: Schätze die Kalorien EXTREM NIEDRIG, DEFENSIV und MINIMALISTISCH.
3. Ziehe im Zweifel gedanklich immer 25% bis 30% vom üblichen Standardvolumen ab. Geh vom absoluten Best-Case-Szenario aus (fettarm zubereitet, moderate Menge).
4. Erstelle einen passenden, zusammenfassenden Namen für das fertige Gericht.

Antworte AUSSCHLIESSLICH im folgenden JSON-Format ohne Codeblöcke oder Text drumherum:
{{"gericht": "Name des fertigen Gerichts auf Deutsch", "kalorien": 400}}"""
                
                # --- WEG B: Es wurde NUR TEXT eingegeben ---
                else:
                    prompt = f"""Du bist ein professioneller Ernährungsberater und Kalorien-Experte.
Der Nutzer hat keine Bilder geschickt, sondern folgenden Text eingegeben: "{text_mahlzeit}"

⚠️ STRENGE REGELN FÜR DIE SCHÄTZUNG:
1. Berechne die Kalorien für diese beschriebene Mahlzeit.
2. Tracke extrem streng: Schätze die Kalorien EXTREM NIEDRIG, DEFENSIV und MINIMALISTISCH.
3. Ziehe im Zweifel gedanklich immer 25% bis 30% von der üblichen Standardportion ab. Geh von einer mageren Zubereitung aus.
4. Nutze als Namen das Gericht (korrigiere eventuell nur Tippfehler).

Antworte AUSSCHLIESSLICH im folgenden JSON-Format ohne Codeblöcke oder Text drumherum:
{{"gericht": "Name des Gerichts auf Deutsch", "kalorien": 400}}"""

                ai_contents.insert(0, prompt)
                
                model = genai.GenerativeModel('gemini-2.5-flash')
                response = model.generate_content(ai_contents)
                
                # Sichere Reinigung
                clean_text = response.text.strip()
                if "```json" in clean_text:
                    clean_text = clean_text.split("```json")[1]
                if "```" in clean_text:
                    clean_text = clean_text.split("```")[0]
                clean_text = clean_text.strip()
                
                daten = json.loads(clean_text)
                
                add_mahlzeit(daten['gericht'], daten['kalorien'], bilder_string_fuer_db)
                
                # Erhöhung des Zählers leert Uploader UND Textfeld
                st.session_state["file_uploader_key"] += 1
                st.success(f"Erfolgreich eingetragen: {daten['gericht']} ({daten['kalorien']} kcal)")
                st.rerun()
                
            except Exception as e:
                st.error(f"Fehler bei der Analyse. Details: {e}")

                # ==========================================
# 5.1 MANUELLE EINGABE (OHNE KI)
# ==========================================
st.write("")
with st.expander("✏️ Mahlzeit manuell eintragen (Ohne KI)", expanded=False):
    manuell_gericht = st.text_input(
        "Was hast du gegessen?", 
        placeholder="z.B. Proteinriegel, Apfel, Haferflocken...",
        key="manuell_gericht_input_neu"
    )
    
    manuell_kalorien = st.number_input(
        "Kalorienanzahl (kcal):", 
        min_value=0, 
        max_value=5000, 
        value=0, 
        step=10,
        key="manuell_kalorien_input_neu"
    )
    
    # HIER IST DER NEUE EINDEUTIGE KEY
    if st.button("💾 Manuell speichern", use_container_width=True, key="absolut_einzigartiger_manuell_speichern_btn_2026"):
        if not manuell_gericht.strip():
            st.warning("Bitte gib einen Namen für das Gericht ein! 😉")
        elif manuell_kalorien <= 0:
            st.warning("Bitte gib die Kalorien an! 😉")
        else:
            try:
                add_mahlzeit(manuell_gericht.strip(), int(manuell_kalorien), "")
                st.success(f"Manuell eingetragen: {manuell_gericht.strip()} ({manuell_kalorien} kcal)")
                st.rerun()
            except Exception as e:
                st.error(f"Fehler beim manuellen Speichern: {e}")
                        
                
# ==========================================
# 6. HEUTIGE MAHLZEITEN (PRO MAHLZEIT ALLE BILDER ANZEIGEN)
# ==========================================
st.subheader("📝 Heutige Mahlzeiten")

if not heutige_mahlzeiten:
    st.info("Noch nichts gegessen heute. Zeit für einen Snack! 🍉")
else:
    for item in heutige_mahlzeiten:
        with st.container(border=True):
            c_img, c_edit, c_del = st.columns([2.5, 4, 1])
            
            with c_img:
                if item.get("bild_data"):
                    try:
                        # Falls mehrere Bilder mit Komma getrennt sind, splitten wir sie hier wieder auf
                        einzelne_bilder = item["bild_data"].split(",")
                        
                        # Wenn es mehrere Bilder gibt, zeigen wir sie in kleinen Spalten nebeneinander an
                        img_cols = st.columns(len(einzelne_bilder))
                        for b_idx, b_data in enumerate(einzelne_bilder):
                            with img_cols[b_idx]:
                                bild_bytes = base64.b64decode(b_data)
                                st.image(Image.open(io.BytesIO(bild_bytes)), use_container_width=True)
                    except:
                        st.caption("🖼️ Bilder")
                else:
                    st.caption(" Kein Bild")
            
            with c_edit:
                with st.expander(f"⚙️ **{item['gericht']}** — {item['kalorien']} kcal", expanded=False):
                    edit_name = st.text_input("Name ändern:", value=item['gericht'], key=f"name_{item['id']}")
                    edit_kcal = st.number_input("Kalorien ändern:", value=int(item['kalorien']), step=10, key=f"kcal_{item['id']}")
                    if st.button("💾 Speichern", key=f"save_{item['id']}", use_container_width=True):
                        update_mahlzeit(item['id'], edit_name, edit_kcal)
                        st.success("Mahlzeit aktualisiert!")
                        st.rerun()
                        
            with c_del:
                st.write("")
                if st.button("🗑️", key=f"del_{item['id']}"):
                    delete_mahlzeit(item['id'])
                    st.rerun()

# ==========================================
# 7. VERLAUF DER LETZTEN TAGE
# ==========================================
st.subheader("📅 Verlauf der letzten Tage")

if not historie:
    st.info("Noch keine Einträge aus den vergangenen Tagen vorhanden.")
else:
    for tag, eintraege in historie.items():
        datum_obj = datetime.strptime(tag, "%Y-%m-%d")
        datum_formatiert = datum_obj.strftime("%d.%m.%Y")
        Tag_gesamtkalorien = sum(e['kalorien'] for e in eintraege)
        
        with st.expander(f"📆 {datum_formatiert} — Gesamt: {Tag_gesamtkalorien} kcal"):
            for item in eintraege:
                c_l, c_r = st.columns([4, 1])
                with c_l:
                    st.write(f"• {item['gericht']} ({item['kalorien']} kcal)")
                with c_r:
                    if st.button("🗑️", key=f"del_hist_{item['id']}"):
                        delete_mahlzeit(item['id'])
                        st.rerun()


# ==========================================
# 7. AUTOMATISCHER WOCHENBERICHT & ARCHIV
# ==========================================
st.divider()
st.subheader("📊 Dein Fitness-Status")

# 1. AUTOMATISCHES AUSLESEN: Wir holen das Tagesziel direkt aus deinem Code/State.
# Falls deine App eine Variable dafür nutzt (z.B. st.session_state['tages_ziel']), liest sie es hier aus.
# Falls nicht, nutzt sie die unten stehenden 2000 kcal als Fallback.
TAGES_ZIEL_KCAL = st.session_state.get("tages_ziel_kcal", st.session_state.get("tages_ziel", 2000))
WOCHEN_ZIEL_KCAL = TAGES_ZIEL_KCAL * 7

# CSS für die fliegenden Emojis (Animationen)
st.markdown("""
<style>
@keyframes flyUp {
    0% { transform: translateY(100vh) translateX(0); opacity: 1; }
    50% { transform: translateY(50vh) translateX(30px); }
    100% { transform: translateY(-10vh) translateX(-30px); opacity: 0; }
}
.emoji-stream {
    position: fixed; left: 50%; top: 0; width: 100%; height: 100vh;
    pointer-events: none; z-index: 9999; overflow: hidden;
}
.animated-emoji {
    position: absolute; font-size: 3rem;
    animation: flyUp 4s linear infinite;
}
</style>
""", unsafe_allow_html=True)

if st.button("📅 Wochenbericht abrufen", use_container_width=True):
    with st.spinner("Berechne Übersicht..."):
        try:
            res = supabase.table("mahlzeiten").select("*").execute()
            alle_eintraege = res.data
            
            if not alle_eintraege:
                st.info("Noch keine Daten für die aktuelle Woche vorhanden.")
            else:
                import datetime
                heute = datetime.date.today()
                vor_einer_woche = heute - datetime.timedelta(days=7)
                
                wochen_kalorien = 0
                for mahlzeit in alle_eintraege:
                    db_datum = datetime.datetime.strptime(mahlzeit["created_at"][:10], "%Y-%m-%d").date()
                    if vor_einer_woche <= db_datum <= heute:
                        wochen_kalorien += int(mahlzeit["kalorien"])
                
                differenz = wochen_kalorien - WOCHEN_ZIEL_KCAL
                
                st.markdown(f"### 🏆 Aktueller Bericht (Basis: {TAGES_ZIEL_KCAL} kcal / Tag)")
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric(label="Ist (Gegessen)", value=f"{wochen_kalorien} kcal")
                with col2:
                    st.metric(label="Soll (Ziel)", value=f"{WOCHEN_ZIEL_KCAL} kcal")
                with col3:
                    # DIE NEUE FARB- UND TEXTLOGIK:
                    if differenz < 0:
                        # Zu wenig gegessen -> ROT leuchtend (Sicherheits-Farbe "inverse")
                        st.metric(
                            label="Defizit (Zuwenig)", 
                            value=f"{differenz} kcal", 
                            delta=f"{abs(differenz)} kcal zu wenig!", 
                            delta_color="inverse" 
                        )
                        # Heulemoji-Regen aktivieren
                        st.markdown('<div class="emoji-stream">'
                                    '<span class="animated-emoji" style="left:20%; animation-delay:0s;">😭</span>'
                                    '<span class="animated-emoji" style="left:40%; animation-delay:1s;">😢</span>'
                                    '<span class="animated-emoji" style="left:60%; animation-delay:0.5s;">😭</span>'
                                    '<span class="animated-emoji" style="left:80%; animation-delay:1.5s;">🐳</span>'
                                    '</div>', unsafe_allow_html=True)
                        st.warning("⚠️ Achtung: Du hast zu wenig gegessen! Pack dir ruhig noch was auf den Teller.")
                        
                    elif differenz == 0:
                        # Exakt getroffen -> GRÜN + Hervorragend
                        st.metric(label="Punktlandung", value="0 kcal", delta="Hervorragend!", delta_color="normal")
                        st.balloons() # Echtes Streamlit-Konfetti werfen!
                        st.success("🎉 Hervorragend! Punktlandung vollbracht!")
                        
                    else:
                        # Zu viel gegessen -> Schulterzucken + Nicht schlimm
                        st.metric(label="Überschuss (Zuviel)", value=f"+{differenz} kcal", delta=f"{differenz} kcal drüber", delta_color="off")
                        # Schulterzucken-Emoji aktivieren
                        st.markdown('<div class="emoji-stream">'
                                    '<span class="animated-emoji" style="left:30%; animation-delay:0s;">🤷‍♂️</span>'
                                    '<span class="animated-emoji" style="left:50%; animation-delay:1.2s;">🤷</span>'
                                    '<span class="animated-emoji" style="left:70%; animation-delay:0.6s;">🤷‍♀️</span>'
                                    '</div>', unsafe_allow_html=True)
                        st.info("🤷 Nicht schlimm! Morgen wird einfach wieder normal weitergetrackt.")
                        
        except Exception as e:
            st.error(f"Fehler beim Laden: {e}")

# ==========================================
# 7. AUTOMATISCHER WOCHENBERICHT (START: MONTAG)
# ==========================================
st.divider()
st.subheader("📊 Dein Fitness-Status")

# DEIN FESTES TÄGLICHES KALORIENZIEL (Hier deine Wunschzahl eintragen!)
TAGES_ZIEL_KCAL = 2000 
WOCHEN_ZIEL_KCAL = TAGES_ZIEL_KCAL * 7

# CSS für die fliegenden Emojis (Animationen)
st.markdown("""
<style>
@keyframes flyUp {
    0% { transform: translateY(100vh) translateX(0); opacity: 1; }
    50% { transform: translateY(50vh) translateX(30px); }
    100% { transform: translateY(-10vh) translateX(-30px); opacity: 0; }
}
.emoji-stream {
    position: fixed; left: 50%; top: 0; width: 100%; height: 100vh;
    pointer-events: none; z-index: 9999; overflow: hidden;
}
.animated-emoji {
    position: absolute; font-size: 3rem;
    animation: flyUp 4s linear infinite;
}
</style>
""", unsafe_allow_html=True)

if st.button("📅 Wochenbericht abrufen", use_container_width=True):
    with st.spinner("Berechne Übersicht ab Montag..."):
        try:
            res = supabase.table("mahlzeiten").select("*").execute()
            alle_eintraege = res.data
            
            if not alle_eintraege:
                st.info("Noch keine Daten für die aktuelle Woche vorhanden.")
            else:
                import datetime
                heute = datetime.date.today()
                
                # Jetzige Woche berechnen: Wir finden den letzten Montag heraus
                # heute.weekday() ist 0 für Montag, 1 für Dienstag, etc.
                letzter_montag = heute - datetime.timedelta(days=heute.weekday())
                
                wochen_kalorien = 0
                for mahlzeit in alle_eintraege:
                    db_datum = datetime.datetime.strptime(mahlzeit["created_at"][:10], "%Y-%m-%d").date()
                    # Wir zählen nur Mahlzeiten, die seit diesem Montag (inklusive) gegessen wurden
                    if letzter_montag <= db_datum <= heute:
                        wochen_kalorien += int(mahlzeit["kalorien"])
                
                differenz = wochen_kalorien - WOCHEN_ZIEL_KCAL
                
                st.markdown(f"### 🏆 Aktueller Bericht (Seit Montag | Ziel: {TAGES_ZIEL_KCAL} kcal / Tag)")
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric(label="Ist (Gegessen)", value=f"{wochen_kalorien} kcal")
                with col2:
                    st.metric(label="Soll (Ziel)", value=f"{WOCHEN_ZIEL_KCAL} kcal")
                with col3:
                    if differenz < 0:
                        # Zu wenig gegessen -> ROT leuchtend
                        st.metric(
                            label="Defizit (Zuwenig)", 
                            value=f"{differenz} kcal", 
                            delta=f"{abs(differenz)} kcal zu wenig!", 
                            delta_color="inverse" 
                        )
                        st.markdown('<div class="emoji-stream">'
                                    '<span class="animated-emoji" style="left:20%; animation-delay:0s;">😭</span>'
                                    '<span class="animated-emoji" style="left:40%; animation-delay:1s;">😢</span>'
                                    '<span class="animated-emoji" style="left:60%; animation-delay:0.5s;">😭</span>'
                                    '</div>', unsafe_allow_html=True)
                        st.warning("⚠️ Achtung: Du hast zu wenig gegessen! Pack dir ruhig noch was auf den Teller.")
                        
                    elif differenz == 0:
                        # Exakt getroffen -> GRÜN + Hervorragend
                        st.metric(label="Punktlandung", value="0 kcal", delta="Hervorragend!", delta_color="normal")
                        st.balloons()
                        st.success("🎉 Hervorragend! Punktlandung vollbracht!")
                        
                    else:
                        # Zu viel gegessen -> Schulterzucken + Nicht schlimm
                        st.metric(label="Überschuss (Zuviel)", value=f"+{differenz} kcal", delta=f"{differenz} kcal drüber", delta_color="off")
                        st.markdown('<div class="emoji-stream">'
                                    '<span class="animated-emoji" style="left:30%; animation-delay:0s;">🤷‍♂️</span>'
                                    '<span class="animated-emoji" style="left:50%; animation-delay:1.2s;">🤷</span>'
                                    '<span class="animated-emoji" style="left:70%; animation-delay:0.6s;">🤷‍♀️</span>'
                                    '</div>', unsafe_allow_html=True)
                        st.info("🤷 Nicht schlimm! Morgen wird einfach wieder normal weitergetrackt.")
                        
        except Exception as e:
            st.error(f"Fehler beim Laden: {e}")

# ==========================================
# 7. AUTOMATISCHER WOCHENBERICHT (START: MONTAG)
# ==========================================
st.divider()
st.subheader("📊 Dein Fitness-Status")

# DEIN FESTES TÄGLICHES KALORIENZIEL (Hier deine Wunschzahl eintragen!)
TAGES_ZIEL_KCAL = 1300 
WOCHEN_ZIEL_KCAL = TAGES_ZIEL_KCAL * 7

# CSS für die fliegenden Emojis (Animationen)
st.markdown("""
<style>
@keyframes flyUp {
    0% { transform: translateY(100vh) translateX(0); opacity: 1; }
    50% { transform: translateY(50vh) translateX(30px); }
    100% { transform: translateY(-10vh) translateX(-30px); opacity: 0; }
}
.emoji-stream {
    position: fixed; left: 50%; top: 0; width: 100%; height: 100vh;
    pointer-events: none; z-index: 9999; overflow: hidden;
}
.animated-emoji {
    position: absolute; font-size: 3rem;
    animation: flyUp 4s linear infinite;
}
</style>
""", unsafe_allow_html=True)

if st.button("📅 Wochenbericht abrufen", use_container_width=True):
    with st.spinner("Berechne Übersicht ab Montag..."):
        try:
            res = supabase.table("mahlzeiten").select("*").execute()
            alle_eintraege = res.data
            
            if not alle_eintraege:
                st.info("Noch keine Daten für die aktuelle Woche vorhanden.")
            else:
                import datetime
                heute = datetime.date.today()
                
                # Jetzige Woche berechnen: Wir finden den letzten Montag heraus
                # heute.weekday() ist 0 für Montag, 1 für Dienstag, etc.
                letzter_montag = heute - datetime.timedelta(days=heute.weekday())
                
                wochen_kalorien = 0
                for mahlzeit in alle_eintraege:
                    db_datum = datetime.datetime.strptime(mahlzeit["created_at"][:10], "%Y-%m-%d").date()
                    # Wir zählen nur Mahlzeiten, die seit diesem Montag (inklusive) gegessen wurden
                    if letzter_montag <= db_datum <= heute:
                        wochen_kalorien += int(mahlzeit["kalorien"])
                
                differenz = wochen_kalorien - WOCHEN_ZIEL_KCAL
                
                st.markdown(f"### 🏆 Aktueller Bericht (Seit Montag | Ziel: {TAGES_ZIEL_KCAL} kcal / Tag)")
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric(label="Ist (Gegessen)", value=f"{wochen_kalorien} kcal")
                with col2:
                    st.metric(label="Soll (Ziel)", value=f"{WOCHEN_ZIEL_KCAL} kcal")
                with col3:
                    if differenz < 0:
                        # Zu wenig gegessen -> ROT leuchtend
                        st.metric(
                            label="Defizit (Zuwenig)", 
                            value=f"{differenz} kcal", 
                            delta=f"{abs(differenz)} kcal zu wenig!", 
                            delta_color="inverse" 
                        )
                        st.markdown('<div class="emoji-stream">'
                                    '<span class="animated-emoji" style="left:20%; animation-delay:0s;">😭</span>'
                                    '<span class="animated-emoji" style="left:40%; animation-delay:1s;">😢</span>'
                                    '<span class="animated-emoji" style="left:60%; animation-delay:0.5s;">😭</span>'
                                    '</div>', unsafe_allow_html=True)
                        st.warning("⚠️ Achtung: Du hast zu wenig gegessen! Pack dir ruhig noch was auf den Teller.")
                        
                    elif differenz == 0:
                        # Exakt getroffen -> GRÜN + Hervorragend
                        st.metric(label="Punktlandung", value="0 kcal", delta="Hervorragend!", delta_color="normal")
                        st.balloons()
                        st.success("🎉 Hervorragend! Punktlandung vollbracht!")
                        
                    else:
                        # Zu viel gegessen -> Schulterzucken + Nicht schlimm
                        st.metric(label="Überschuss (Zuviel)", value=f"+{differenz} kcal", delta=f"{differenz} kcal drüber", delta_color="off")
                        st.markdown('<div class="emoji-stream">'
                                    '<span class="animated-emoji" style="left:30%; animation-delay:0s;">🤷‍♂️</span>'
                                    '<span class="animated-emoji" style="left:50%; animation-delay:1.2s;">🤷</span>'
                                    '<span class="animated-emoji" style="left:70%; animation-delay:0.6s;">🤷‍♀️</span>'
                                    '</div>', unsafe_allow_html=True)
                        st.info("🤷 Nicht schlimm! Morgen wird einfach wieder normal weitergetrackt.")
                        
        except Exception as e:
            st.error(f"Fehler beim Laden: {e}")

# ==========================================
# AUTOMATISCHER FIXER WOCHENVERLAUF (ARCHIV)
# ==========================================
st.write("")
st.markdown("### 📁 Archivierte Wochenberichte")

try:
    res = supabase.table("mahlzeiten").select("*").execute()
    alle_daten = res.data

    if alle_daten:
        import datetime
        from collections import defaultdict
        
        wochen_gruppen = defaultdict(list)
        
        for mahlzeit in alle_daten:
            db_datum = datetime.datetime.strptime(mahlzeit["created_at"][:10], "%Y-%m-%d").date()
            jahr, kw, _ = db_datum.isocalendar()
            wochen_gruppen[f"Jahr {jahr} - Kalenderwoche {kw}"].append(mahlzeit)
            
        for woche_name, mahlzeiten_der_woche in sorted(wochen_gruppen.items(), reverse=True):
            gesamte_wochen_kcal = sum(int(m["kalorien"]) for m in mahlzeiten_der_woche)
            wochen_soll = WOCHEN_ZIEL_KCAL
            diff = gesamte_wochen_kcal - wochen_soll
            
            if diff < 0:
                status_text = f"🔴 {gesamte_wochen_kcal} kcal / {wochen_soll} kcal (Zu wenig)"
            elif diff == 0:
                status_text = f"🟢 {gesamte_wochen_kcal} kcal (Hervorragend!)"
            else:
                status_text = f"⚪ {gesamte_wochen_kcal} kcal / {wochen_soll} kcal (Nicht schlimm)"
                
            with st.expander(f"📅 {woche_name} ➔ {status_text}"):
                st.write(f"**Zusammenfassung:**")
                st.write(f"• Insgesamt gegessen: `{gesamte_wochen_kcal} kcal`")
                st.write(f"• Wochen-Soll: `{wochen_soll} kcal`")
                st.write(f"• Abweichung: `{diff} kcal`")
                
                st.write("**Details dieser Woche:**")
                for m in mahlzeiten_der_woche:
                    st.write(f"• {m['created_at'][:10]} | *{m['gericht']}* ({m['kalorien']} kcal)")
except Exception as e:
    st.error(f"Fehler beim Generieren des Archivs: {e}")
