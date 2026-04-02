from flask import Flask, render_template, request, redirect, url_for, flash, Response, session, send_file
import psycopg2
import os
from dotenv import load_dotenv
from datetime import datetime
import csv
import io
import gzip
import json

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "supersecret")

# ---------------- UTILS ----------------

def get_conn():
    """
    Récupère la connexion à partir de l'URL stockée en session.
    """
    db_url = session.get('custom_db_url')
    if not db_url:
        return None, "Aucune base de données connectée. Veuillez entrer une URL."
    try:
        conn = psycopg2.connect(db_url)
        return conn, None
    except Exception as e:
        return None, str(e)

def get_primary_key(table, conn):
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT a.attname
            FROM   pg_index i
            JOIN   pg_attribute a ON a.attrelid = i.indrelid
                                 AND a.attnum = ANY(i.indkey)
            WHERE  i.indrelid = %s::regclass
            AND    i.indisprimary;
        """, (table,))
        result = cur.fetchone()
        return result[0] if result else None
    except:
        return None

# ---------------- ROUTES ----------------

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        db_url = request.form.get("db_url")
        if not db_url:
            flash("Veuillez saisir une URL valide", "error")
            return redirect(url_for("home"))
        try:
            # Test de connexion immédiat
            conn = psycopg2.connect(db_url)
            conn.close()
            session['custom_db_url'] = db_url
            flash("✅ Connexion réussie !", "success")
            return redirect(url_for("db_dashboard"))
        except Exception as e:
            flash(f"Erreur de connexion : {e}", "error")
            return redirect(url_for("home"))

    return render_template("home.html", connected_db=session.get('custom_db_url'))

@app.route("/logout")
def logout():
    session.pop('custom_db_url', None)
    flash("Déconnecté de la base de données", "success")
    return redirect(url_for("home"))

@app.route("/dashboard")
def db_dashboard():
    conn, err = get_conn()
    if err:
        flash(err, "error")
        return redirect(url_for("home"))
    
    try:
        cur = conn.cursor()
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
        tables = [t[0] for t in cur.fetchall()]
        
        selected_table = request.args.get("table")
        columns = []
        rows_dicts = []

        if selected_table:
            cur.execute(f'SELECT * FROM "{selected_table}" ORDER BY 1 DESC LIMIT 50')
            data = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
            rows_dicts = [dict(zip(columns, row)) for row in data]

        conn.close()
        return render_template(
            "dashboard.html",
            db_key="Active DB",
            tables=tables,
            columns=columns,
            rows_dicts=rows_dicts,
            selected_table=selected_table
        )
    except Exception as e:
        flash(f"Erreur SQL: {e}", "error")
        return redirect(url_for("home"))

# ---------------- ACTIONS (CRUD) ----------------

@app.route("/table/<table>/insert", methods=["POST"])
def insert_row(table):
    conn, err = get_conn()
    if err: return redirect(url_for("home"))
    try:
        cur = conn.cursor()
        columns = request.form.getlist("col[]")
        values = request.form.getlist("val[]")
        col_names = ", ".join([f'"{c}"' for c in columns])
        placeholders = ", ".join(["%s"] * len(values))
        cur.execute(f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders})', values)
        conn.commit()
        flash("✅ Ligne insérée !", "success")
    except Exception as e:
        flash(f"❌ Erreur: {e}", "error")
    return redirect(url_for("db_dashboard", table=table))

@app.route("/table/<table>/update", methods=["POST"])
def update_row(table):
    conn, err = get_conn()
    if err: return redirect(url_for("home"))
    try:
        cur = conn.cursor()
        pk_col = get_primary_key(table, conn)
        row_id = request.form.get("row_id")
        columns = [k for k in request.form.keys() if k not in ["row_id"]]
        values = [request.form[k] for k in columns]
        set_clause = ", ".join([f'"{col}"=%s' for col in columns])
        cur.execute(f'UPDATE "{table}" SET {set_clause} WHERE "{pk_col}"=%s', values + [row_id])
        conn.commit()
        flash("✅ Ligne modifiée !", "success")
    except Exception as e:
        flash(f"❌ Erreur: {e}", "error")
    return redirect(url_for("db_dashboard", table=table))

@app.route("/table/<table>/delete/<pk>", methods=["POST"])
def delete_row(table, pk):
    conn, err = get_conn()
    if err: return redirect(url_for("home"))
    try:
        cur = conn.cursor()
        pk_col = get_primary_key(table, conn)
        cur.execute(f'DELETE FROM "{table}" WHERE "{pk_col}" = %s', (pk,))
        conn.commit()
        flash("✅ Ligne supprimée !", "success")
    except Exception as e:
        flash(f"❌ Erreur: {e}", "error")
    return redirect(url_for("db_dashboard", table=table))

# ---------------- IMPORT / EXPORT ----------------
@app.route("/export_sql")
def export_sql():
    conn, err = get_conn()
    if err: return redirect(url_for("home"))
    
    try:
        cur = conn.cursor()
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
        tables = [t[0] for t in cur.fetchall()]
        
        sql_output = f"-- DB Backup Render-Compatible (JSON FIX) - {datetime.now()}\n"
        sql_output += "BEGIN;\n\n"

        for table in tables:
            sql_output += f'DROP TABLE IF EXISTS "{table}" CASCADE;\n'
            
            # Récupération structure
            cur.execute("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns 
                WHERE table_name = %s 
                ORDER BY ordinal_position
            """, (table,))
            columns_info = cur.fetchall()
            
            sql_output += f'CREATE TABLE "{table}" (\n'
            col_defs = []
            for col in columns_info:
                name, dtype, nullable, default = col
                if default and 'nextval' in default:
                    line = f'    "{name}" {"BIGSERIAL" if "bigint" in dtype else "SERIAL"}'
                else:
                    line = f'    "{name}" {dtype}'
                    if nullable == "NO": line += " NOT NULL"
                    if default: line += f" DEFAULT {default}"
                col_defs.append(line)
            sql_output += ",\n".join(col_defs) + "\n);\n\n"

            # Récupération Données
            cur.execute(f'SELECT * FROM "{table}"')
            rows = cur.fetchall()
            if rows:
                col_names = [desc[0] for desc in cur.description]
                col_str = ", ".join([f'"{c}"' for c in col_names])
                
                for row in rows:
                    vals = []
                    for v in row:
                        if v is None:
                            vals.append("NULL")
                        elif isinstance(v, (dict, list)):
                            # --- FIX JSON ICI ---
                            # On force le format JSON correct avec doubles guillemets
                            json_str = json.dumps(v)
                            # On échappe les simples quotes SQL
                            vals.append(f"'{json_str.replace("'", "''")}'")
                        elif isinstance(v, bool):
                            vals.append("true" if v else "false")
                        elif isinstance(v, (int, float)):
                            vals.append(str(v))
                        else:
                            # Pour tout le reste (text, varchar, date)
                            # On convertit en string et on échappe les quotes SQL
                            escaped = str(v).replace("'", "''")
                            vals.append(f"'{escaped}'")
                    
                    sql_output += f'INSERT INTO "{table}" ({col_str}) VALUES ({", ".join(vals)});\n'
                
                if "id" in col_names:
                    sql_output += f"SELECT setval(pg_get_serial_sequence('\"{table}\"', 'id'), coalesce(MAX(id), 1)) FROM \"{table}\";\n"
            
            sql_output += "\n"

        sql_output += "COMMIT;\n"
        conn.close()
        
        # Compression Gzip (Contourne le 403 Forbidden de Render)
        mem = io.BytesIO()
        with gzip.GzipFile(fileobj=mem, mode='wb') as f:
            f.write(sql_output.encode('utf-8'))
        mem.seek(0)
        
        return send_file(mem, as_attachment=True, download_name=f"render_json_fix.sql.gz", mimetype="application/gzip")

    except Exception as e:
        flash(f"❌ Erreur export: {e}", "error")
        return redirect(url_for("db_dashboard"))
    
@app.route("/import_sql", methods=["POST"])
def import_sql():
    file = request.files.get('sql_file')
    if not file:
        flash("Aucun fichier", "error")
        return redirect(url_for("db_dashboard"))
    
    conn, err = get_conn()
    if err: return redirect(url_for("home"))
    
    try:
        # Si le fichier finit par .gz, on le décompresse
        if file.filename.endswith('.gz'):
            with gzip.open(file, 'rb') as f:
                content = f.read().decode('utf-8')
        else:
            content = file.read().decode('utf-8')
            
        with conn.cursor() as cur:
            cur.execute(content)
        
        conn.commit()
        conn.close()
        flash("✅ Importation réussie (via tunnel compressé) !", "success")
    except Exception as e:
        if conn: conn.rollback()
        flash(f"❌ Erreur import: {e}", "error")
        
    return redirect(url_for("db_dashboard"))

@app.route("/table/<table>/export_csv")
def export_csv(table):
    conn, err = get_conn()
    if err: return redirect(url_for("home"))
    try:
        cur = conn.cursor()
        cur.execute(f'SELECT * FROM "{table}"')
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(columns)
        writer.writerows(rows)
        
        mem = io.BytesIO()
        mem.write(output.getvalue().encode('utf-8'))
        mem.seek(0)
        return send_file(mem, as_attachment=True, download_name=f"{table}.csv", mimetype="text/csv")
    except Exception as e:
        flash(f"Erreur CSV: {e}", "error")
        return redirect(url_for("db_dashboard", table=table))

if __name__ == "__main__":
    app.run(port=5001, debug=True)