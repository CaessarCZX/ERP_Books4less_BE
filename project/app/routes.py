from flask import Blueprint, jsonify, request
from app.services import download_file, process_file, upload_csv_to_supabase
from app import db
from app.models import Inventory

main = Blueprint('main', __name__)

@main.route('/download/<filename>', methods=['GET'])
def download_file_from_supabase(filename):
    try:
        # Obtener la URL firmada de Supabase
        response = download_file(filename)  # Usamos la función importada de `services.py`

        if isinstance(response, dict) and 'error' in response:
            return jsonify(response), 500

        # Procesar y subir el archivo corregido
        process_file(response)
        upload_csv_to_supabase(response)

        return jsonify({"message": f"Archivo {filename} descargado, procesado y subido correctamente."}), 200

    except Exception as e:
        return jsonify({"error": f"Excepción al procesar el archivo: {str(e)}"}), 500

@main.route('/check_connection')
def check_connection():
    """ Verifica la conexión con Supabase """
    try:
        data = db.session.query(Inventory).all()
        return jsonify({"message": "Conexión exitosa", "data": [item.__dict__ for item in data]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
