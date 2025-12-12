from flask import Flask, render_template, request, redirect, url_for, flash
import psycopg2
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "supersecret")

APP_ENV = os.getenv("APP_ENV", "local")
USE_INTERNAL = APP_ENV == "render"

DATABASES = {
    "vie_anterieure": {
        "internal": os.getenv("DB_VIE_ANTERIEURE_INTERNAL"),
        "external": os.getenv("DB_VIE_ANTERIEURE_EXTERNAL"),
    },
}

def get_db_url(db_key):
    db = DATABASES.get(db_key)
    if not db:
        return None
    return db["internal"] if USE_INTERNAL else db["external"]

def get_conn(db_key):
    url = get_db_url(db_key)
    if not url:
        return None, f"URL DB manquante pour '{db_key}'"
    try:
        conn = psycopg2.connect(url)
        return conn, None
    except Exception as e:
        return None, str(e)

def get_primary_key(table, conn):
    cur = conn.cursor()
    cur.execute(f"""
        SELECT a.attname
        FROM   pg_index i
        JOIN   pg_attribute a ON a.attrelid = i.indrelid
                             AND a.attnum = ANY(i.indkey)
        WHERE  i.indrelid = '{table}'::regclass
        AND    i.indisprimary;
    """)
    result = cur.fetchone()
    return result[0] if result else None

# CREATE
@app.route("/db/<db_key>/table/<table>/insert", methods=["POST"])
def insert_row(db_key, table):
    conn, err = get_conn(db_key)
    if err:
        flash(f"Erreur connexion: {err}", "error")
        return redirect(url_for("db_dashboard", db_key=db_key, table=table))
    try:
        cur = conn.cursor()
        columns = request.form.getlist("col[]")
        values = request.form.getlist("val[]")
        col_names = ", ".join([f'"{c}"' for c in columns])
        placeholders = ", ".join(["%s"] * len(values))
        cur.execute(f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders})', values)
        conn.commit()
        conn.close()
        flash("✅ Ligne insérée avec succès !", "success")
    except Exception as e:
        flash(f"❌ Erreur insertion: {e}", "error")
    return redirect(url_for("db_dashboard", db_key=db_key, table=table))

# DELETE
@app.route("/db/<db_key>/table/<table>/delete/<pk>", methods=["POST"])
def delete_row(db_key, table, pk):
    conn, err = get_conn(db_key)
    if err:
        flash(f"Erreur connexion: {err}", "error")
        return redirect(url_for("db_dashboard", db_key=db_key, table=table))
    try:
        cur = conn.cursor()
        pk_col = get_primary_key(table, conn)
        cur.execute(f'DELETE FROM "{table}" WHERE "{pk_col}" = %s', (pk,))
        conn.commit()
        conn.close()
        flash("✅ Ligne supprimée !", "success")
    except Exception as e:
        flash(f"❌ Erreur suppression: {e}", "error")
    return redirect(url_for("db_dashboard", db_key=db_key, table=table))

# UPDATE
@app.route("/db/<db_key>/table/<table>/update", methods=["POST"])
def update_row(db_key, table):
    conn, err = get_conn(db_key)
    if err:
        flash(f"Erreur connexion: {err}", "error")
        return redirect(url_for("db_dashboard", db_key=db_key, table=table))
    try:
        cur = conn.cursor()
        pk_col = get_primary_key(table, conn)
        row_id = request.form.get("row_id")
        columns = [k for k in request.form.keys() if k != "row_id"]
        values = [request.form[k] for k in columns]
        set_clause = ", ".join([f'"{col}"=%s' for col in columns])
        cur.execute(f'UPDATE "{table}" SET {set_clause} WHERE "{pk_col}"=%s', values + [row_id])
        conn.commit()
        conn.close()
        flash("✅ Ligne modifiée !", "success")
    except Exception as e:
        flash(f"❌ Erreur modification: {e}", "error")
    return redirect(url_for("db_dashboard", db_key=db_key, table=table))

# DASHBOARD
@app.route("/db/<db_key>")
def db_dashboard(db_key):
    if db_key not in DATABASES:
        return f"DB '{db_key}' inconnue", 404
    conn, err = get_conn(db_key)
    if err:
        return f"Erreur connexion: {err}"
    try:
        cur = conn.cursor()
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        tables = [t[0] for t in cur.fetchall()]
        selected_table = request.args.get("table")
        data = []
        columns = []
        rows_dicts = []

        if selected_table:
            cur.execute(f"SELECT * FROM {selected_table} ORDER BY 1 DESC LIMIT 50")
            data = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
            # Transforme chaque ligne en dictionnaire pour le template
            rows_dicts = [dict(zip(columns, row)) for row in data]

        conn.close()
        return render_template(
            "dashboard.html",
            db_key=db_key,
            tables=tables,
            data=data,
            columns=columns,
            rows_dicts=rows_dicts,
            selected_table=selected_table,
            mode="internal" if USE_INTERNAL else "external"
        )
    except Exception as e:
        return f"Erreur SQL: {e}"

@app.route("/")
def home():
    db_display = {key: get_db_url(key) for key in DATABASES.keys()}
    return render_template("home.html", dbs=db_display)

if __name__ == "__main__":
    app.run(port=5001, debug=True)