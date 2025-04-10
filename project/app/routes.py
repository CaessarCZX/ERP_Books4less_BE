from flask import Blueprint, jsonify, request, send_file
from app.services import upload_to_supabase, download_file_from_supabase, process_file, create_pdf, create_csv, delete_old_files
from app import db
import os
import uuid
import traceback
import pandas as pd
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from app.supabase_client import supabase
import io
import bcrypt
import jwt


main = Blueprint('main', __name__)

# Carpetas locales (no se modifican)
DOWNLOAD_FOLDER = "downloads"
UPLOAD_FOLDER = "uploads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Limpieza de archivos antiguos
delete_old_files()


# para el login
# Debes tener definida en tu configuración una clave secreta
SECRET_KEY = "marioputo"  # Cambia esto por tu clave segura
ALGORITHM = "HS256"

@main.route('/download/pdf', methods=['GET'])
def download_pdf():
    """
    Endpoint para descargar un PDF subido.
    Se espera recibir el parámetro 'filename' en la query string.
    Ejemplo: /download/pdf?filename=1234_20250403_131200_output.pdf
    """
    filename = request.args.get('filename')
    if not filename:
        return jsonify({"error": "Parámetro 'filename' no proporcionado."}), 400

    file_path = os.path.join(DOWNLOAD_FOLDER, filename)
    if not os.path.exists(file_path):
        # También se puede intentar descargar desde Supabase si el archivo no está local
        download_result = download_file_from_supabase(f"pdf/{filename}")
        if isinstance(download_result, dict) and "error" in download_result:
            return jsonify(download_result), 500
        file_path = download_result

    try:
        return send_file(file_path, as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@main.route('/download/csv', methods=['GET'])
def download_csv():
    """
    Endpoint para descargar un CSV subido.
    Se espera recibir el parámetro 'filename' en la query string.
    Ejemplo: /download/csv?filename=1234_20250403_131200_output.csv
    """
    filename = request.args.get('filename')
    if not filename:
        return jsonify({"error": "Parámetro 'filename' no proporcionado."}), 400

    file_path = os.path.join(DOWNLOAD_FOLDER, filename)
    if not os.path.exists(file_path):
        # También se puede intentar descargar desde Supabase si el archivo no está local
        download_result = download_file_from_supabase(f"csv/{filename}")
        if isinstance(download_result, dict) and "error" in download_result:
            return jsonify(download_result), 500
        file_path = download_result

    try:
        return send_file(file_path, as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
    
def consolidate_files(file_paths):
    """
    Lee todos los archivos en file_paths (soportados: CSV y XLSX),
    los concatena en un único DataFrame y lo guarda en un archivo Excel temporal.
    Se usa para consolidar los datos de múltiples archivos.
    """
    dfs = []
    for path in file_paths:
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext == ".xlsx":
                df = pd.read_excel(path, engine="openpyxl")
            elif ext == ".csv":
                # Intentamos leer el CSV de varias maneras
                try:
                    df = pd.read_csv(path, delimiter=",", engine="python")
                except Exception as e:
                    try:
                        df = pd.read_csv(path, delimiter=";", engine="python")
                    except Exception as e:
                        print(f"Error leyendo {path}: {e}")
                        continue
            else:
                continue
            dfs.append(df)
        except Exception as e:
            print(f"Error leyendo {path}: {e}")
            continue
    if not dfs:
        return None, "No se pudo leer ningún archivo válido."
    consolidated_df = pd.concat(dfs, ignore_index=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    consolidated_file = os.path.join(DOWNLOAD_FOLDER, f"{timestamp}_consolidated.xlsx")
    consolidated_df.to_excel(consolidated_file, index=False)
    return consolidated_file, None

@main.route('/api/process-all', methods=['POST'])
def process_all():
    """
    Ruta unificada que:
      - Recibe múltiples archivos y datos del formulario.
      - Sube cada archivo a Supabase y lo registra en la BD.
      - Consolida los datos de todos los archivos en un único archivo Excel.
      - A partir de ese archivo consolidado genera el CSV y el PDF usando las funciones
        create_csv y create_pdf (definidas en services.py) sin alterar su lógica.
      - Sube los archivos generados (CSV y PDF) a Supabase y retorna sus nombres.
    """
    try:
        # Validar campos obligatorios
        discount_rate = request.form.get('discount_rate')
        if not discount_rate:
            return jsonify({"error": "discount_rate es obligatorio."}), 400
        try:
            discount_rate = float(discount_rate)
        except ValueError:
            return jsonify({"error": "discount_rate debe ser numérico."}), 400

        # Otros datos del formulario (se usan en el PDF)
        form_data = {
            "purchase_info": request.form.get('purchase_info', ''),
            "order_date": request.form.get('order_date', ''),
            "seller_name": request.form.get('seller_name', ''),
            "seller_PO": request.form.get('seller_PO', ''),
            "seller_address": request.form.get('seller_address', ''),
            "company_name": request.form.get('company_name', ''),
            "company_address": request.form.get('company_address', ''),
            "company_info": request.form.get('company_info', ''),
            "shipping_method": request.form.get('shipping_method', ''),
            "payment_terms": request.form.get('payment_terms', '')
        }

        files = request.files.getlist('files')
        if not files:
            return jsonify({"error": "No se han enviado archivos."}), 400

        allowed_extensions = ['csv', 'xlsx']
        temp_file_paths = []
        errors = []
        # duplicate_files = []
        uploaded_files = []
        renamed_files = []  # Para registrar archivos renombrados

        # Procesar cada archivo recibido
        for file in files:
            if not file:
                continue
            original_filename = file.filename.strip()
            ext = original_filename.split('.')[-1].lower()
            if ext not in allowed_extensions:
                errors.append({"file": original_filename, "error": "Formato no soportado."})
                continue

            # Generar nombre seguro con user_id, timestamp y nombre original
            # timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            base_name = secure_filename(original_filename.rsplit('.', 1)[0])
            # new_filename = f"{timestamp}_{base_name}.{ext}"
            new_filename = f"{base_name}.{ext}"


            
            # Verificar si el nombre ya existe en la base de datos
           

            temp_path = os.path.join(UPLOAD_FOLDER, new_filename)
            file.save(temp_path)
            temp_file_paths.append(temp_path)

            # Subir a Supabase y registrar en la BD
            supa_path = f"xlsx/{new_filename}"
            if upload_to_supabase(temp_path, supa_path) is None:
                errors.append({"file": original_filename, "error": "Error al subir a Supabase."})
                os.remove(temp_path)
                continue

           
            uploaded_files.append({
                'original_name': original_filename,  # Guardamos el original solo en la respuesta
                'stored_name': new_filename
            })
        
      

        if not temp_file_paths:
            return jsonify({"error": "No se pudo procesar ningún archivo válido.", "details": errors}), 400

        # Consolidar todos los archivos en uno solo
        consolidated_file, consolidate_error = consolidate_files(temp_file_paths)
        if consolidate_error:
            return jsonify({"error": consolidate_error}), 500

        # Generar el CSV consolidado
        # timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        excel_base = secure_filename(files[0].filename.rsplit('.', 1)[0])
        csv_filename = f"{excel_base}.csv"
        csv_path = os.path.join(DOWNLOAD_FOLDER, csv_filename)
        csv_result = create_csv(consolidated_file, csv_path)
        if "error" in csv_result:
            return jsonify(csv_result), 500

        # Generar el PDF consolidado
        pdf_filename = f"{excel_base}.pdf"
        pdf_path = os.path.join(DOWNLOAD_FOLDER, pdf_filename)
        pdf_result = create_pdf(consolidated_file, pdf_path, discount_rate, form_data)
        if "error" in pdf_result:
            return jsonify(pdf_result), 500

        # Subir CSV y PDF a Supabase
        upload_to_supabase(csv_path, f"csv/{csv_filename}")
        upload_to_supabase(pdf_path, f"pdf/{pdf_filename}")

        # Limpiar archivos temporales (archivos individuales y el consolidado)
        for path in temp_file_paths:
            if os.path.exists(path):
                os.remove(path)
        if os.path.exists(consolidated_file):
            os.remove(consolidated_file)

        return jsonify({
            "message": "Procesamiento completado exitosamente.",
            "uploaded_files": uploaded_files,
            "renamed_files": renamed_files,  # Informar sobre archivos renombrados
            "csv": csv_filename,
            "pdf": pdf_filename,
            "errors": errors
        }), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    
@main.route('/api/files', methods=['GET'])
def list_files():
    """
    Lista todos los archivos dentro del bucket 'uploads' en Supabase,
    incluyendo archivos en la raíz, 'pdf/' y 'csv/', ignorando carpetas y archivos ocultos.
    """
    try:
        carpetas = ['xlsx/', 'pdf/', 'csv/']
        archivos = []

        for carpeta in carpetas:
            files = supabase.storage.from_('uploads').list(carpeta)

            for file in files:
                nombre_archivo = file["name"]

                # Ignorar archivos ocultos (ej: .emptyFolderPlaceholder) o sin metadata
                if nombre_archivo.startswith('.') or not file.get("metadata"):
                    continue

                ext = nombre_archivo.split('.')[-1].lower()
                tipo = (
                    'pdf' if ext == 'pdf' else
                    'csv' if ext == 'csv' else
                    'excel' if ext == 'xlsx' else
                    'otro'
                )

                archivos.append({
                    "nombre": nombre_archivo,
                    "carpeta": carpeta if carpeta else "root",
                    "tipo": tipo,
                    "fecha_subida": file.get("created_at", "No disponible"),
                    "tamano": round(file["metadata"].get("size", 0) / 1024 / 1024, 2),
                    "url_descarga": f"http://127.0.0.1:5000/download?carpeta={carpeta}&filename={nombre_archivo}"
                })

        return jsonify(archivos), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    
@main.route('/download')
def descargar_archivo():
    carpeta = request.args.get('carpeta', '')
    filename = request.args.get('filename', '')

    if not filename:
        return "Archivo no especificado", 400

    ruta = f"{carpeta}{filename}"

    try:
        # Descarga el archivo desde Supabase
        res = supabase.storage.from_('uploads').download(ruta)

        # Forzar descarga desde el navegador
        return send_file(
            io.BytesIO(res),
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        traceback.print_exc()
        return f"Error al descargar: {str(e)}", 500
    


@main.route('/api/login', methods=['POST'])
def login_user():
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')
        
        # Validar que ambos campos estén presentes
        if not email or not password:
            return jsonify({"error": "El email y la contraseña son obligatorios."}), 400

        # Buscar el usuario en la base de datos (se seleccionan id, email y password)
        user_query = supabase.table('users').select('id, email, password').eq('email', email).execute()
        if not user_query.data or len(user_query.data) == 0:
            return jsonify({"error": "Usuario no encontrado."}), 404

        # Obtener el primer registro (se asume que el email es único)
        user = user_query.data[0]
        user_id = user.get('id')
        stored_hashed = user.get('password')

        # Comparar la contraseña enviada con la almacenada (hasheada)
        if not bcrypt.checkpw(password.encode('utf-8'), stored_hashed.encode('utf-8')):
            return jsonify({"error": "Contraseña incorrecta."}), 401

        # Generar token de login válido por 5 minutos
        login_payload = {
            "user_id": user_id,
            "email": email,
            "exp": datetime.utcnow() + timedelta(minutes=5)
        }
        login_token = jwt.encode(login_payload, SECRET_KEY, algorithm=ALGORITHM)

        # Generar token de sesión válido por 1 día
        session_payload = {
            "user_id": user_id,
            "email": email,
            "exp": datetime.utcnow() + timedelta(days=1)
        }
        session_token = jwt.encode(session_payload, SECRET_KEY, algorithm=ALGORITHM)

        return jsonify({
            "login_token": login_token,
            "session_token": session_token,
            "user_id": user_id,
            "email": email
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

@main.route('/api/register', methods=['POST'])
def register_user():
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')
        confirm_password = data.get('confirm_password')

        if not email or not password or not confirm_password:
            return jsonify({'error': 'Todos los campos son obligatorios.'}), 400

        if password != confirm_password:
            return jsonify({'error': 'Las contraseñas no coinciden.'}), 400

        # Verificar si el correo ya está registrado
        existing_user = supabase.table('users').select('email').eq('email', email).execute()
        if existing_user.data:
            return jsonify({'error': 'El correo ya está registrado.'}), 400

        # Hashear la contraseña
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        # Insertar en Supabase
        result = supabase.table('users').insert({
            'email': email,
            'password': hashed_password,
            'is_admin': False
        }).execute()

        # Convertir el APIResponse a diccionario
        result_dict = result.dict()
        
        # Verificar si se encontró un error en el resultado
        if result_dict.get('error'):
            return jsonify({'error': result_dict.get('error')}), 500

        # Obtener el ID del usuario recién creado
        user_id = result_dict['data'][0]['id']

        return jsonify({'message': 'Usuario registrado exitosamente.', 'user_id': user_id}), 201

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    
@main.route('/api/change-password', methods=['POST'])
def change_password():
    try:
        data = request.json
        email = data.get('email')
        new_password = data.get('new_password')
        confirm_new_password = data.get('confirm_new_password')

        # Verificar que se envíen todos los campos
        if not email or not new_password or not confirm_new_password:
            return jsonify({'error': 'Todos los campos son obligatorios.'}), 400

        # Validar que las contraseñas coincidan
        if new_password != confirm_new_password:
            return jsonify({'error': 'Las contraseñas no coinciden.'}), 400

        # Verificar si el usuario existe en la base de datos
        user_query = supabase.table('users').select('id').eq('email', email).execute()
        if not user_query.data or len(user_query.data) == 0:
            return jsonify({'error': 'Usuario no encontrado.'}), 404

        # Hashear la nueva contraseña
        hashed_new_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        # Actualizar la contraseña del usuario en Supabase
        update_result = supabase.table('users').update({
            'password': hashed_new_password
        }).eq('email', email).execute()

        # Convertir la respuesta a diccionario para poder acceder a "error"
        result_dict = update_result.dict()
        if result_dict.get('error'):
            return jsonify({'error': result_dict.get('error')}), 500

        return jsonify({'message': 'Contraseña actualizada exitosamente.'}), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500