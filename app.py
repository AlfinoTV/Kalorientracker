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

GOOGLE_API_KEY = "AQ.Ab8RN6LOTJL7P7ayrCUzoW7oaScrfp69O2ebr5CrnX_3w3iVvg"
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
    res = supabase.table("mahlzeiten").select("*").order("created_at", desc=True).execute()
    return res.data if res.data else []

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
# 5. KI MULTI-UPLOAD (ZUSAMMENRECHNEN + ALLE BILDER SPEICHERN)
# ==========================================
st.subheader("📸 Mahlzeit tracken")

if "file_uploader_key" not in st.session_state:
    st.session_state["file_uploader_key"] = 0

uploaded_files = st.file_uploader(
    "Wähle alle Bilder deiner Zutaten aus (z.B. Brot, Soße, Käse)...", 
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
    key=f"uploader_{st.session_state['file_uploader_key']}"
)

if uploaded_files:
    # Bilder anzeigen
    cols = st.columns(len(uploaded_files))
    for idx, file in enumerate(uploaded_files):
        with cols[idx]:
            img = Image.open(file)
            st.image(img, caption=f"Zutat {idx+1}", use_container_width=True)
            
    zusatz_info = st.text_input("💡 Zusatzinfos zu den Zutaten:", placeholder="z.B. 2 Scheiben Brot, 1 EL Soße, 2 Scheiben Käse...")
    
    if st.button("🚀 Gesamte Mahlzeit zusammenrechnen & speichern", use_container_width=True):
        with st.spinner("KI rechnet alle Zutaten zu einer Mahlzeit zusammen..."):
            try:
                ai_contents = []
                alle_bilder_base64 = []
                
                # Wir gehen durch alle Bilder durch
                for file in uploaded_files:
                    image = Image.open(file)
                    img_byte_arr = io.BytesIO()
                    image.save(img_byte_arr, format=image.format if image.format else 'JPEG')
                    img_bytes = img_byte_arr.getvalue()
                    
                    # Jedes einzelne Bild in Base64 umwandeln und in der Liste sammeln
                    b64_str = base64.b64encode(img_bytes).decode('utf-8')
                    alle_bilder_base64.append(b64_str)
                    
                    ai_contents.append({
                        "mime_type": f"image/{image.format.lower() if image.format else 'jpeg'}",
                        "data": img_bytes
                    })
                
                # Alle Bilder-Texte mit einem Komma verbinden, um sie zusammen in EINER Tabellenzelle zu speichern
                bilder_string_fuer_db = ",".join(alle_bilder_base64)
                
                prompt = f"""Du bist ein professioneller Ernährungsberater und Kalorien-Experte. 
                Die beigefügten Bilder zeigen die einzelnen ZUTATEN (Anzahl: {len(uploaded_files)}) für EINE EINZIGE gemeinsame Mahlzeit (z.B. die Komponenten eines Burgers, belegten Brots oder Gerichts).
                
                Kritische Nutzer-Zusatzinfo: "{zusatz_info}"
                
                ⚠️ STRENGE REGELN FÜR DIE SCHÄTZUNG:
                1. Schätze die Kalorien für jede Zutat einzeln und addiere sie zu einem Gesamtwert für die MAHLZEIT.
                2. Tracke extrem streng: Schätze die Kalorien EXTREM NIEDRIG, DEFENSIV und MINIMALISTISCH.
                3. Ziehe im Zweifel gedanklich immer 25% bis 30% vom üblichen Standardvolumen ab. Geh vom absoluten Best-Case-Szenario aus (fettarm zubereitet, moderate Menge).
                4. Erstelle einen passenden, zusammenfassenden Namen für das fertige Gericht (z.B. 'Belegtes Käsebrot mit Soße').
                
                Antworte AUSSCHLIESSLICH im folgenden JSON-Format ohne Codeblöcke oder Text drumherum:
                {{"gericht": "Name des fertigen Gerichts auf Deutsch", "kalorien": 400}}"""
                
                ai_contents.insert(0, prompt)
                
                model = genai.GenerativeModel('gemini-2.5-flash')
                response = model.generate_content(ai_contents)
                
                clean_text = response.text.replace("```json", "").replace("```", "").strip()
                daten = json.loads(clean_text)
                
                # Als EINE Mahlzeit mit ALLEN Bildern speichern
                add_mahlzeit(daten['gericht'], daten['kalorien'], bilder_string_fuer_db)
                
                st.session_state["file_uploader_key"] += 1
                st.success(f"Erfolgreich als eine Mahlzeit eingetragen: {daten['gericht']} ({daten['kalorien']} kcal)")
                st.rerun()
                
            except Exception as e:
                st.error(f"Fehler bei der Analyse. Details: {e}")

st.divider()

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