from flask import Blueprint, jsonify, request
from app.services import download_file, process_file, create_pdf, upload_to_supabase, create_csv, delete_old_files
from app import db
from app.models import Inventory, UserFiles  # UserFiles debe ser un modelo para registrar los archivos subidos
from app.models import Inventory
import os
import uuid
import traceback
from werkzeug.utils import secure_filename
from datetime import datetime



main = Blueprint('main', __name__)

DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

UPLOAD_FOLDER = "uploads"  # Carpeta donde se guardarán los archivos temporalmente

# Asegúrate de que la carpeta de subida exista
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

@main.route('/upload', methods=['POST'])
def upload_files():
    """Permite subir múltiples archivos asociados a un usuario, 
    asegurando que no se suban archivos duplicados para el mismo usuario."""
    try:
        user_id = request.form.get('user_id')
        files = request.files.getlist('file')  # Obtener todos los archivos

        if not files or not user_id:
            return jsonify({"error": "No se proporcionaron archivos o user_id"}), 400

        allowed_extensions = {'csv', 'xlsx'}
        uploaded_files = []
        duplicate_files = []
        errors = []

        for file in files:
            if not file:
                continue

            filename = secure_filename(file.filename)
            extension = filename.split('.')[-1].lower()

            # Validar la extensión del archivo
            if extension not in allowed_extensions:
                errors.append({"file": filename, "error": "Formato de archivo no soportado"})
                continue

            # Verificar si el archivo ya existe en la base de datos para este usuario
            existing_file = UserFiles.query.filter_by(user_id=user_id, filename=filename).first()
            if existing_file:
                duplicate_files.append(filename)
                continue

            # Guardar el archivo temporalmente
            temp_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(temp_path)

            try:
                # Subir el archivo a Supabase Storage
                upload_result = upload_to_supabase(temp_path, f"uploads/{user_id}/{filename}")

                if upload_result is None:
                    errors.append({"file": filename, "error": "Error al subir a Supabase"})
                else:
                    # Registrar el archivo en la base de datos
                    new_file = UserFiles(user_id=user_id, filename=filename)
                    db.session.add(new_file)
                    db.session.commit()
                    uploaded_files.append(filename)

            except Exception as e:
                errors.append({"file": filename, "error": str(e)})

            finally:
                # Eliminar el archivo temporal
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except PermissionError:
                        errors.append({"file": filename, "error": "No se pudo eliminar el archivo temporal."})

        return jsonify({
            "uploaded_files": uploaded_files,
            "duplicate_files": duplicate_files,
            "errors": errors
        }), 200

    except Exception as e:
        print("Error al subir archivos:", str(e))
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    
@main.route('/download/<file_id>', methods=['GET'])
def download_user_file(file_id):
    """Permite a un usuario descargar su archivo mediante su ID."""
    try:
        user_id = request.args.get('user_id')  # Validar al usuario
        if not user_id:
            return jsonify({"error": "ID de usuario no proporcionado."}), 400

        # Buscar el archivo en la base de datos
        user_file = UserFiles.query.filter_by(id=file_id, user_id=user_id).first()
        if not user_file:
            return jsonify({"error": "Archivo no encontrado o no autorizado."}), 404

        # Descargar desde Supabase Storage
        file_path = f"user_files/{user_id}/{user_file.filename}"
        download_result = download_file(file_path, DOWNLOAD_FOLDER)
        if "error" in download_result:
            return jsonify(download_result), 500

        # Retornar el archivo al usuario
        local_path = os.path.join(DOWNLOAD_FOLDER, user_file.filename)
        return send_file(local_path, as_attachment=True)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@main.route('/api/create-pdf', methods=['POST'])
def generate_pdf():
    try:
        data = request.json
        user_id = data.get("user_id")
        if not user_id:
            return jsonify({"error": "user_id no proporcionado."}), 400

        # Obtener todos los archivos del usuario
        user_files = UserFiles.query.filter_by(user_id=user_id).all()
        if not user_files:
            return jsonify({"error": "No se encontraron archivos para este usuario."}), 404

        # Tomar el archivo más reciente
        latest_file = user_files[-1].filename
        
        local_file_path = os.path.join(DOWNLOAD_FOLDER, latest_file)

        # Si el archivo no está local, descargarlo de Supabase
        if not os.path.exists(local_file_path):
            download_result = download_file(f"uploads/{user_id}/{latest_file}")
            if isinstance(download_result, dict) and "error" in download_result:
                return jsonify({"error": download_result['error']}), 500
            local_file_path = download_result

        # Procesar el archivo antes de generar el PDF
        processed_file = process_file(local_file_path, discount_percent=float(data.get("discount_rate", 3)))
        if "error" in processed_file:
            return jsonify(processed_file), 500

        # Generar el nombre del PDF
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_pdf_name = f"{user_id}_{timestamp}_output.pdf"
        output_pdf = os.path.join(DOWNLOAD_FOLDER, output_pdf_name)

        # Crear el PDF con el archivo procesado
        pdf_result = create_pdf(processed_file, output_pdf, discount_percent=float(data.get("discount_rate", 3)), form_data=data)
        if "error" in pdf_result:
            return jsonify(pdf_result), 500

        # Subir el PDF a Supabase
        try:
            upload_pdf = upload_to_supabase(output_pdf, f"pdf/{user_id}/{output_pdf_name}")
        except Exception as e:
            if 'Duplicate' in str(e):
                # Manejar el error de duplicado, renombrando el archivo
                output_pdf_name = f"{user_id}_{timestamp}_{str(uuid.uuid4())}_output.pdf"
                upload_pdf = upload_to_supabase(output_pdf, f"pdf/{user_id}/{output_pdf_name}")
            else:
                return jsonify({"error": f"Error al subir el PDF: {str(e)}"}), 500

        return jsonify({
            "message": f"PDF generado y subido exitosamente.",
            "pdf": output_pdf_name
        }), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Error en la generación del PDF: {str(e)}"}), 500

# Llamada para limpiar archivos antiguos, si es necesario
delete_old_files()

@main.route('/api/create-csv', methods=['POST'])
def generate_csv():
    """
    Genera un CSV procesado a partir del archivo subido por el usuario.
    """
    try:
        data = request.json
        user_id = data.get("user_id")
        if not user_id:
            return jsonify({"error": "user_id no proporcionado."}), 400

        # Obtener el archivo del usuario (se toma el más reciente)
        user_files = UserFiles.query.filter_by(user_id=user_id).all()
        if not user_files:
            return jsonify({"error": "No se encontraron archivos para este usuario."}), 404

        latest_file = user_files[-1].filename
        local_file_path = os.path.join(DOWNLOAD_FOLDER, latest_file)
        
        # Descargar el archivo si no existe localmente
        if not os.path.exists(local_file_path):
            download_result = download_file(f"uploads/{user_id}/{latest_file}")
            if isinstance(download_result, dict) and "error" in download_result:
                return jsonify(download_result), 500
            local_file_path = download_result

        # Definir la ruta del CSV procesado
        output_csv = os.path.join(DOWNLOAD_FOLDER, f"{user_id}_output.csv")

        # Crear el CSV usando la función ya definida (create_csv)
        csv_result = create_csv(local_file_path, output_csv)
        if "error" in csv_result:
            return jsonify(csv_result), 500

        # Opcional: Subir el CSV a Supabase (por ejemplo, a un bucket 'csv')
        upload_csv = upload_to_supabase(output_csv, f"csv/{user_id}/{os.path.basename(output_csv)}")
        if upload_csv is None or ("error" in upload_csv):
            return jsonify({"error": "CSV creado, pero error al subir a Supabase."}), 500

        return jsonify({
            "message": f"CSV generado y subido exitosamente.",
            "csv": os.path.basename(output_csv)
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@main.route('/check_connection')
def check_connection():
    """ Verifica la conexión con Supabase """
    try:
        data = db.session.query(Inventory).all()
        return jsonify({"message": "Conexión exitosa", "data": [item.__dict__ for item in data]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
