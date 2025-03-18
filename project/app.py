from flask import Flask, jsonify
from supabase import create_client, Client
from dotenv import load_dotenv
import os

# Cargar las variables de entorno desde el archivo .env
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")

# Crear el cliente de Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_API_KEY)

app = Flask(__name__)

@app.route('/check_connection')
def check_connection():
    try:
        # Intentar realizar una consulta simple
        response = supabase.table('inventory').select('*').execute()

        # Extraer directamente la clave 'data'
        data = response.data

        if data:
            return jsonify({
                "message": "Conexion exitosa a Supabase",
                "data": data
            })
        else:
            return jsonify({
                "message": "Conexion exitosa, pero no hay datos en la tabla 'inventory'."
            })

    except Exception as e:
        # Si hay un error al conectar o ejecutar la consulta
        return jsonify({
            "error": "Error al conectar con Supabase",
            "details": str(e)
        }), 500

if __name__ == "__main__":
    app.run(debug=True)
