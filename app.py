import os
import psycopg2
from flask import Flask, render_template, request, redirect
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# --- MULTI DATABASES: ajoute autant que tu veux ---
DATABASES = {
    "vie_anterieure": os.getenv("DB_VIE_ANTERIEURE"),
    # "mon_autre_projet": os.getenv("DB_OTHER_PROJECT"),
    # tu peux en rajouter ici
}

def get_conn(db_key):
    try:
        url = DATABASES[db_key]
        return psycopg2.connect(url)
    except Exception as e:
        return None, str(e)


@app.route("/")
def home():
    return render_template("home.html", dbs=DATABASES)


@app.route("/db/<db_key>")
def db_dashboard(db_key):

    if db_key not in DATABASES:
        return f"DB '{db_key}' inconnue", 404

    try:
        conn = psycopg2.connect(DATABASES[db_key])
        cur = conn.cursor()

        # Récupérer les tables
        cur.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema='public'
        """)
        tables = [t[0] for t in cur.fetchall()]

        selected_table = request.args.get("table")
        data = []
        columns = []

        if selected_table:
            cur.execute(f"SELECT * FROM {selected_table} ORDER BY 1 DESC LIMIT 50")
            data = cur.fetchall()
            columns = [desc[0] for desc in cur.description]

        conn.close()

        return render_template(
            "dashboard.html",
            db_key=db_key,
            tables=tables,
            data=data,
            columns=columns,
            selected_table=selected_table
        )

    except Exception as e:
        return f"❌ Erreur connexion: {e}"


if __name__ == "__main__":
    app.run(port=5001, debug=True)
