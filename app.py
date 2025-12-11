import os
import psycopg2
from flask import Flask, render_template, request
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# --- Détection : LOCAL vs RENDER ---
APP_ENV = os.getenv("APP_ENV", "local")  # "local" par défaut
USE_INTERNAL = APP_ENV == "render"

print("====================================")
print("🚀 MODE D'EXÉCUTION :", "Render (Internal DB)" if USE_INTERNAL else "Local (External DB)")
print("====================================")

# --- BASES DISPONIBLES ---
DATABASES = {
    "vie_anterieure": {
        "internal": os.getenv("DB_VIE_ANTERIEURE_INTERNAL"),
        "external": os.getenv("DB_VIE_ANTERIEURE_EXTERNAL"),
    },
}

# ----------- SELECT AUTO INTERNAL / EXTERNAL ---------------
def get_db_url(db_key):
    db = DATABASES.get(db_key)
    if not db:
        return None

    url = db["internal"] if USE_INTERNAL else db["external"]
    print(f"🔍 DB sélectionnée : {db_key} → {'internal' if USE_INTERNAL else 'external'}")
    print(f"🔗 URL utilisée : {url}")
    return url


def get_conn(db_key):
    url = get_db_url(db_key)
    if not url:
        return None, f"URL DB manquante pour '{db_key}'"

    print(f"📡 Tentative de connexion à '{db_key}'...")

    try:
        conn = psycopg2.connect(url)
        print("✅ Connexion réussie !")
        return conn, None

    except Exception as e:
        print("❌ ERREUR CONNEXION :", e)
        return None, str(e)


# ----------- ROUTES ----------------
@app.route("/")
def home():
    db_display = {
        key: get_db_url(key)
        for key in DATABASES.keys()
    }
    return render_template("home.html", dbs=db_display)

@app.route("/db/<db_key>")
def db_dashboard(db_key):

    if db_key not in DATABASES:
        print(f"❌ DB inconnue : {db_key}")
        return f"DB '{db_key}' inconnue", 404

    conn, err = get_conn(db_key)
    if err:
        print(f"❌ Impossible de se connecter à {db_key} :", err)
        return f"❌ Erreur connexion: {err}"

    try:
        cur = conn.cursor()

        print("📥 Récupération des tables...")
        cur.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema='public'
        """)
        tables = [t[0] for t in cur.fetchall()]
        print(f"📌 Tables trouvées : {tables}")

        selected_table = request.args.get("table")
        data = []
        columns = []

        if selected_table:
            print(f"📄 Lecture de la table : {selected_table}")
            cur.execute(f"SELECT * FROM {selected_table} ORDER BY 1 DESC LIMIT 50")
            data = cur.fetchall()
            columns = [desc[0] for desc in cur.description]

        conn.close()
        print("🔒 Connexion fermée proprement.")

        return render_template(
            "dashboard.html",
            db_key=db_key,
            tables=tables,
            data=data,
            columns=columns,
            selected_table=selected_table,
            mode="internal" if USE_INTERNAL else "external"
        )

    except Exception as e:
        print("❌ ERREUR SQL/Dashboard :", e)
        return f"❌ Erreur: {e}"


if __name__ == "__main__":
    app.run(port=5001, debug=True)
# ----------- FIN DU FICHIER ----------------