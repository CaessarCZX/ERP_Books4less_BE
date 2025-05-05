
import io
import os
import uuid
import traceback
import time
import bcrypt
import jwt
import pandas as pd
from app import db
from functools import wraps
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from supabase import create_client
from config.config import Config
from flask import Blueprint, jsonify, request, current_app, make_response, send_file
from app.services import upload_to_supabase, download_file_from_supabase, process_file, create_pdf, create_csv, delete_old_files



supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_API_KEY)


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
SECRET_KEY = "clavesupersecretanomanches"  # Cambia esto por tu clave segura
ALGORITHM = "HS256"

@main.route('/', methods=['GET'])
def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Backend Desplegado</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                text-align: center;
                margin-top: 50px;
                background-color: #f5f5f5;
            }
            .container {
                background-color: white;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 0 10px rgba(0,0,0,0.1);
                max-width: 600px;
                margin: 0 auto;
            }
            h1 {
                color: #2c3e50;
            }
            .status {
                color: #27ae60;
                font-weight: bold;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Backend de ERP Books4less</h1>
            <p>El backend se ha desplegado correctamente en Azure.</p>
            <p class="status">Estado: Funcionando</p>
            <p>Resource Group: POManager</p>
            <p>Ubicación: East US 2</p>
        </div>
    </body>
    </html>
    """

# decorador para autenticacion de usuario 
def token_required(role=None):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            token = None

            # Buscar token en el header
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]

            # Si no viene en el header, buscar en cookies
            if not token:
                token = request.cookies.get('login_token') or request.cookies.get('session_token')

            if not token:
                return jsonify({"error": "Token no proporcionado."}), 401

            try:
                payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            except jwt.ExpiredSignatureError:
                return jsonify({"error": "Token expirado."}), 401
            except jwt.InvalidTokenError:
                return jsonify({"error": "Token inválido."}), 401

            if role:
                if payload.get("role") != role:
                    return jsonify({"error": "Acceso denegado. Permiso insuficiente."}), 403

            request.user = payload
            return f(*args, **kwargs)
        return wrapped
    return decorator

# @token_required()  # cualquier usuario autenticado
# @token_required(role='admin')  # solo admins

@main.route('/api/upload-excel', methods=['POST'])
def upload_excel():
    """
    Endpoint para subir múltiples archivos Excel a Supabase.
    Los archivos se guardan en la carpeta 'xlsx/{user_id}/'
    """
    try:
        # Verificar que se hayan enviado archivos
        if 'files' not in request.files:
            return jsonify({"error": "No se han enviado archivos"}), 400
            
        files = request.files.getlist('files')  # Lista de archivos
        user_id = request.form.get('user_id')
        
        # Validaciones básicas
        if not user_id:
            return jsonify({"error": "El parámetro user_id es requerido"}), 400
            
        if len(files) == 0:
            return jsonify({"error": "No se proporcionaron archivos"}), 400
            
        response_data = []
        temp_dir = os.path.join(UPLOAD_FOLDER, "temp_uploads")
        os.makedirs(temp_dir, exist_ok=True)

        for file in files:
            # Validar cada archivo individualmente
            if file.filename == '':
                response_data.append({
                    "filename": file.filename,
                    "error": "Nombre de archivo vacío",
                    "success": False
                })
                continue
                
            # Verificar extensión
            file_extension = os.path.splitext(file.filename)[1].lower()
            if file_extension not in ['.xlsx', '.xls']:
                response_data.append({
                    "filename": file.filename,
                    "error": "Formato no permitido (solo .xlsx, .xls)",
                    "success": False
                })
                continue
            
            # Procesar archivo válido
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                original_filename = secure_filename(file.filename)
                new_filename = f"{os.path.splitext(original_filename)[0]}_{timestamp}{file_extension}"
                temp_path = os.path.join(temp_dir, new_filename)
                
                file.save(temp_path)
                
                # Subir a Supabase
                destination_path = f"xlsx/{user_id}/{new_filename}"
                upload_success = upload_to_supabase(temp_path, destination_path)
                
                # Obtener URL pública (opcional)
                file_url = ""
                if upload_success:
                    try:
                        file_url = supabase.storage.from_('uploads').get_public_url(destination_path)
                    except Exception as url_error:
                        print(f"Error al obtener URL: {url_error}")
                
                # Registrar respuesta
                response_data.append({
                    "success": upload_success,
                    "filename": new_filename,
                    "original_filename": original_filename,
                    "file_url": file_url if upload_success else "",
                    "destination_path": destination_path if upload_success else "",
                    "error": "" if upload_success else "Error al subir a Supabase"
                })
                
            except Exception as file_error:
                response_data.append({
                    "filename": file.filename,
                    "error": f"Error procesando archivo: {str(file_error)}",
                    "success": False
                })
                
            finally:
                # Limpieza del archivo temporal
                if 'temp_path' in locals():
                    try:
                        os.remove(temp_path)
                    except Exception as cleanup_error:
                        print(f"Error limpiando archivo temporal: {cleanup_error}")

        # Estadísticas del proceso
        success_count = sum(1 for item in response_data if item['success'])
        
        return jsonify({
            "message": f"Proceso completado ({success_count}/{len(files)} archivos subidos)",
            "results": response_data,
            "total_files": len(files),
            "successful_uploads": success_count,
            "failed_uploads": len(files) - success_count
        }), 200 if success_count > 0 else 207  # 207 = Multi-Status
        
    except Exception as e:
        return jsonify({
            "error": "Error interno del servidor",
            "details": str(e)
        }), 500

@main.route('/api/logout', methods=['POST'])
def logout():
    response = make_response(jsonify({"message": "Sesión cerrada"}), 200)
    response.delete_cookie('login_token')
    response.delete_cookie('session_token')
    return response

@main.route('/api/login', methods=['POST'])
def login_user():
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')
        
        if not email or not password:
            return jsonify({"error": "El email y la contraseña son obligatorios."}), 400

        user_query = supabase.table('users').select('id, email, password, is_admin').eq('email', email).execute()
        if not user_query.data or len(user_query.data) == 0:
            return jsonify({"error": "Usuario no encontrado."}), 404

        user = user_query.data[0]
        user_id = user.get('id')
        stored_hashed = user.get('password')

        if not bcrypt.checkpw(password.encode('utf-8'), stored_hashed.encode('utf-8')):
            return jsonify({"error": "Contraseña incorrecta."}), 401

        is_admin = user.get('is_admin', False)

        login_payload = {
            "user_id": user_id,
            "email": email,
            "role": "admin" if is_admin else "user", 
            "exp": datetime.utcnow() + timedelta(minutes=5)
        }
        login_token = jwt.encode(login_payload, SECRET_KEY, algorithm=ALGORITHM)

        session_payload = {
            "user_id": user_id,
            "email": email,
            "role": "admin" if is_admin else "user",
            "exp": datetime.utcnow() + timedelta(days=1)
        }
        session_token = jwt.encode(session_payload, SECRET_KEY, algorithm=ALGORITHM)

        # Crear la respuesta con los datos visibles en JSON si quieres, o vacía si solo usas cookies
        response = make_response(jsonify({
            "message": "Login exitoso",
            "user_id": user_id,
            "email": email,
            "isAdmin": is_admin,
        }), 200)

        # Agregar las cookies
        response.set_cookie("login_token", login_token, httponly=True, secure=True, samesite='Strict', max_age=300)
        response.set_cookie("session_token", session_token, httponly=True, secure=True, samesite='Strict', max_age=86400)

        return response

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
    

@main.route('/api/protected', methods=['GET'])
def protected_route():
    try:
        # Leer el token desde la cookie
        session_token = request.cookies.get('session_token')

        if not session_token:
            return jsonify({"error": "Token de sesión no encontrado."}), 401

        # Decodificar y verificar el token
        payload = jwt.decode(session_token, SECRET_KEY, algorithms=[ALGORITHM])

        # Puedes acceder a los datos del usuario desde el payload
        user_id = payload.get('user_id')
        email = payload.get('email')

        return jsonify({
            "message": "Acceso concedido",
            "user_id": user_id,
            "email": email
        }), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "El token ha expirado."}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Token inválido."}), 401

@main.route('/api/reference-items', methods=['GET'])
def get_reference_items():
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({"error": "user_id es requerido"}), 400

        response = supabase.table('item_reference')\
            .select('*')\
            .eq('user_id', user_id)\
            .order('item_number')\
            .execute()

        return jsonify({
            "total_items": len(response.data),
            "items": response.data
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@main.route('/api/upload-reference', methods=['POST'])
def upload_reference():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "El archivo es requerido"}), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({"error": "Nombre de archivo no válido"}), 400

        ext = file.filename.split('.')[-1].lower()
        if ext not in ['csv', 'xlsx']:
            return jsonify({"error": "Formato no soportado"}), 400

        try:
            if ext == 'xlsx':
                df = pd.read_excel(file)
            else:
                sample = file.stream.read(1024).decode('utf-8')
                file.stream.seek(0)
                delimiter = ',' if ',' in sample else ';'
                df = pd.read_csv(file, delimiter=delimiter)
                
            print(f"Registros totales en archivo: {len(df)}")
            
            df.columns = df.columns.str.strip().str.lower()
            if not all(col in df.columns for col in ['no.', 'description']):
                return jsonify({"error": "El archivo debe contener columnas 'No.' y 'Description'"}), 400

            # Limpieza y conversión segura a tipos nativos
            df = df[['no.', 'description']].fillna({'no.': '', 'description': ''})
            df['no.'] = df['no.'].astype(str).str.strip()
            df['description'] = df['description'].astype(str).str.strip()

            # Preparar registros asegurando tipos serializables
            records = []
            for _, row in df.iterrows():
                records.append({
                    'item_number': str(row['no.']),
                    'description': str(row['description']),
                    'source_file': secure_filename(file.filename)
                })

            print(f"Registros preparados para inserción: {len(records)}")

            try:
                # Eliminar existentes
                supabase.table('item_reference').delete().neq('id', 0).execute()
                
                if records:
                    batch_size = 1000
                    total_inserted = 0
                    
                    for i in range(0, len(records), batch_size):
                        batch = records[i:i + batch_size]
                        response = supabase.table('item_reference').insert(batch).execute()
                        if response.data:
                            total_inserted += len(response.data)
                    
                    print(f"Registros insertados exitosamente: {total_inserted}")
                    return jsonify({
                        "message": f"Base de datos actualizada. {total_inserted} items subidos",
                        "total_items": total_inserted
                    }), 200
                else:
                    return jsonify({
                        "message": "Base de datos vaciada. No hay datos para insertar.",
                        "total_items": 0
                    }), 200
                    
            except Exception as e:
                current_app.logger.error(f"Error en inserción: {str(e)}", exc_info=True)
                return jsonify({
                    "error": "Error al actualizar la base de datos",
                    "details": str(e)
                }), 500

        except Exception as e:
            return jsonify({"error": f"Error al procesar archivo: {str(e)}"}), 400

    except Exception as e:
        current_app.logger.error(f"Error inesperado: {str(e)}", exc_info=True)
        return jsonify({
            "error": "Error interno del servidor",
            "details": str(e)
        }), 500
        
def consolidate_files(file_paths):
    """
    Consolida archivos validando estructura y calculando campos adicionales.
    """
    dfs = []
    for path in file_paths:
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext == ".xlsx":
                df = pd.read_excel(path, engine="openpyxl")
            elif ext == ".csv":
                try:
                    df = pd.read_csv(path, delimiter=",", engine="python")
                except:
                    df = pd.read_csv(path, delimiter=";", engine="python")
            else:
                continue
                
            # Validar y calcular campos adicionales para cada archivo
            if 'us_price' in df.columns and 'quantity' in df.columns:
                df['us_price'] = pd.to_numeric(df['us_price'], errors='coerce').fillna(0)
                df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0)
                df['Extended Retail'] = df['quantity'] * df['us_price']
                
            dfs.append(df)
        except Exception as e:
            print(f"Error procesando {path}: {e}")
            continue
            
    if not dfs:
        return None, "No se pudo leer ningún archivo válido."
        
    consolidated_df = pd.concat(dfs, ignore_index=True)
    
    # Guardar el archivo consolidado procesado
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    consolidated_file = os.path.join(DOWNLOAD_FOLDER, f"{timestamp}_consolidado_procesado.xlsx")
    consolidated_df.to_excel(consolidated_file, index=False)
    
    return consolidated_file, None

@main.route('/api/process-all', methods=['POST'])
def process_all():
    """
    Endpoint para procesar archivos y generar reportes PDF/CSV
    - Compara los item_id del archivo con item_number de item_reference
    - Muestra estadísticas de coincidencias
    - Identifica qué archivos no están en la tabla de referencia
    """
    try:
        # Validación inicial
        start_time = time.time()
        user_id = request.form.get('user_id')
        discount_rate = request.form.get('discount_rate')
        
        if not user_id or not discount_rate:
            return jsonify({"error": "user_id y discount_rate son obligatorios."}), 400
        
        try:
            discount_rate = float(discount_rate)
        except ValueError:
            return jsonify({"error": "discount_rate debe ser numérico."}), 400

        # Función para formatear fecha (solo día/mes/año)
        def format_date(date_str):
            try:
                if not date_str:
                    return 'N/A'
                if 'T' in date_str:
                    date_part = date_str.split('T')[0]
                    date_obj = datetime.strptime(date_part, "%Y-%m-%d")
                else:
                    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                return date_obj.strftime("%m/%d/%Y")
            except:
                return date_str

        # Datos del formulario con fecha formateada
        form_data = {
            "purchase_info": request.form.get('purchase_info', ''),
            "order_date": format_date(request.form.get('order_date', '')),
            "seller_name": request.form.get('seller_name', ''),
            "seller_PO": request.form.get('seller_PO', ''),
            "seller_address": request.form.get('seller_address', ''),
            "company_name": request.form.get('company_name', ''),
            "company_address": request.form.get('company_address', ''),
            "company_info": request.form.get('company_info', ''),
            "shipping_method": request.form.get('shipping_method', ''),
            "payment_terms": request.form.get('payment_terms', '')
        }

        # Procesamiento de archivos
        files = request.files.getlist('files')
        if not files:
            return jsonify({"error": "No se han enviado archivos."}), 400

        # Generar timestamp único para nombres de archivo
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 1. Obtener datos de referencia
        reference_time = time.time()
        try:
            reference_response = supabase.table('item_reference')\
                .select('item_number,description').execute()
            reference_items = pd.DataFrame(reference_response.data if reference_response.data else [])
            reference_set = set(reference_items['item_number'].astype(str).str.strip()) if not reference_items.empty else set()
        except Exception as e:
            current_app.logger.error(f"Error al obtener referencia: {str(e)}")
            reference_items = pd.DataFrame()
            reference_set = set()
        
        current_app.logger.info(f"Tiempo carga referencia: {time.time() - reference_time:.2f}s")

        # 2. Procesar archivos subidos
        upload_time = time.time()
        temp_file_paths = []
        errors = []
        uploaded_files = []
        all_processed_items = set()

        for file in files:
            if not file:
                continue
                
            original_filename = file.filename.strip()
            ext = original_filename.split('.')[-1].lower()
            
            if ext not in ['csv', 'xlsx']:
                errors.append({"file": original_filename, "error": "Formato no soportado."})
                continue

            try:
                # Crear nombre único con timestamp
                base_name = secure_filename(original_filename.rsplit('.', 1)[0])
                new_filename = f"{base_name}_{timestamp}.{ext}"
                temp_path = os.path.join(UPLOAD_FOLDER, new_filename)
                file.save(temp_path)
                temp_file_paths.append(temp_path)

                # Leer archivo y extraer item_ids
                if ext == 'xlsx':
                    df = pd.read_excel(temp_path)
                else:
                    sample = file.stream.read(1024).decode('utf-8')
                    file.stream.seek(0)
                    delimiter = ',' if ',' in sample else ';'
                    df = pd.read_csv(temp_path, delimiter=delimiter)
                
                # Normalizar nombres de columnas
                df.columns = df.columns.str.strip().str.lower()
                
                # Buscar columna que contiene los IDs (item_id, no., etc.)
                id_column = None
                for col in ['item_id', 'no.', 'no', 'item_number', 'number']:
                    if col in df.columns:
                        id_column = col
                        break
                
                if id_column:
                    items_in_file = set(df[id_column].astype(str).str.strip())
                    all_processed_items.update(items_in_file)
                
                # Subir a Supabase
                supa_path = f"xlsx/{user_id}/{new_filename}"
                upload_to_supabase(temp_path, supa_path)
                uploaded_files.append({
                    'original_name': original_filename,
                    'stored_name': new_filename
                })
                
            except Exception as e:
                errors.append({"file": original_filename, "error": str(e)})
                continue

        if not temp_file_paths:
            return jsonify({"error": "No se pudo procesar ningún archivo válido.", "details": errors}), 400

        current_app.logger.info(f"Tiempo subida archivos: {time.time() - upload_time:.2f}s")

        # 3. Consolidar archivos
        consolidate_time = time.time()
        consolidated_file, consolidate_error = consolidate_files(temp_file_paths)
        if consolidate_error:
            return jsonify({"error": consolidate_error}), 500
        current_app.logger.info(f"Tiempo consolidación: {time.time() - consolidate_time:.2f}s")

        # 4. Generar CSV
        csv_time = time.time()
        excel_base = secure_filename(files[0].filename.rsplit('.', 1)[0])
        csv_filename = f"{excel_base}_{timestamp}.csv"
        csv_path = os.path.join(DOWNLOAD_FOLDER, csv_filename)
        
        try:
            csv_result = create_csv(consolidated_file, csv_path)
            if "error" in csv_result:
                return jsonify(csv_result), 500
            upload_to_supabase(csv_path, f"csv/{user_id}/{csv_filename}")
        except Exception as e:
            current_app.logger.error(f"Error al generar CSV: {str(e)}")
            return jsonify({"error": "Error al generar CSV", "details": str(e)}), 500
        
        current_app.logger.info(f"Tiempo generación CSV: {time.time() - csv_time:.2f}s")

        # 5. Generar PDF
        pdf_time = time.time()
        pdf_filename = f"{excel_base}_{timestamp}.pdf"
        pdf_path = os.path.join(DOWNLOAD_FOLDER, pdf_filename)
        
        try:
            pdf_result = create_pdf(consolidated_file, pdf_path, discount_rate, form_data)
            if "error" in pdf_result:
                return jsonify(pdf_result), 500
            upload_to_supabase(pdf_path, f"pdf/{user_id}/{pdf_filename}")
        except Exception as e:
            current_app.logger.error(f"Error al generar PDF: {str(e)}")
            return jsonify({"error": "Error al generar PDF", "details": str(e)}), 500
        
        current_app.logger.info(f"Tiempo generación PDF: {time.time() - pdf_time:.2f}s")

        # 6. Comparación mejorada que maneja ceros a la izquierda
        compare_time = time.time()

        # Obtener TODOS los item_number de la referencia conservando ceros a la izquierda
        try:
            # Consulta paginada para manejar grandes volúmenes
            reference_items = []
            page = 0
            while True:
                response = supabase.table('item_reference')\
                    .select('item_number')\
                    .range(page*1000, (page+1)*1000-1)\
                    .execute()
                if not response.data:
                    break
                # Conservar los valores exactos como strings (incluyendo ceros a la izquierda)
                reference_items.extend([str(item['item_number']) for item in response.data])
                page += 1
            
            # Crear dos versiones del conjunto de referencia:
            # 1. Original (conserva ceros a la izquierda)
            reference_set_original = set(reference_items)
            # 2. Normalizado (sin ceros a la izquierda para comparación flexible)
            reference_set_normalized = set([item.lstrip('0') for item in reference_items])
            
        except Exception as e:
            current_app.logger.error(f"Error al obtener referencia: {str(e)}")
            reference_items = []
            reference_set_original = set()
            reference_set_normalized = set()

        # Extraer TODOS los item_id de los archivos Excel conservando ceros a la izquierda
        all_processed_items_original = set()
        all_processed_items_normalized = set()
        file_item_mapping = {}

        for file_path in temp_file_paths:
            try:
                df = pd.read_excel(file_path)
                
                # Buscar la columna item_id (exactamente ese nombre)
                if 'item_id' not in df.columns:
                    # Si no existe, buscar columnas alternativas
                    id_col = next((col for col in df.columns if col.lower() in ['item_id', 'no.', 'item_number', 'number']), None)
                else:
                    id_col = 'item_id'
                
                if id_col:
                    # Convertir a string y limpiar espacios
                    df[id_col] = df[id_col].astype(str).str.strip()
                    
                    # Procesar cada item
                    for item in df[id_col].dropna().unique():
                        # Conservar versión original
                        all_processed_items_original.add(item)
                        # Crear versión normalizada (sin ceros a la izquierda)
                        normalized_item = item.lstrip('0')
                        all_processed_items_normalized.add(normalized_item)
                        
                        # Mapeo para trazabilidad
                        if item not in file_item_mapping:
                            file_item_mapping[item] = []
                        file_item_mapping[item].append(os.path.basename(file_path))
                            
            except Exception as e:
                current_app.logger.error(f"Error procesando archivo {file_path}: {str(e)}")
                continue

        # Realizar comparaciones considerando ceros a la izquierda
        unmatched_items = set()

        # Primera pasada: comparación exacta (incluyendo ceros a la izquierda)
        exact_matches = all_processed_items_original & reference_set_original

        # Segunda pasada: comparación normalizada (sin ceros a la izquierda)
        normalized_matches = all_processed_items_normalized & reference_set_normalized

        # Identificar items no coincidentes
        for item in all_processed_items_original:
            # Verificar si no coincide ni exactamente ni en versión normalizada
            if item not in exact_matches and item.lstrip('0') not in normalized_matches:
                unmatched_items.add(item)

        # Construcción del resultado
        comparison_results = {
            "total_reference_items": len(reference_set_original),
            "total_processed_items": len(all_processed_items_original),
            "matched_items_count": len(exact_matches) + len(normalized_matches) - len(set([i.lstrip('0') for i in exact_matches]) & set([i.lstrip('0') for i in normalized_matches])),  # Evitar duplicados
            "unmatched_items": [{"item_id": item, "source_files": file_item_mapping.get(item, [])} for item in unmatched_items],
            "match_percentage": round((len(all_processed_items_original) - len(unmatched_items)) / len(all_processed_items_original) * 100, 2) if all_processed_items_original else 0,
            "files_with_missing_references": list(set(f for item in unmatched_items for f in file_item_mapping.get(item, []))),
            "validation_notes": {
                "exact_matches": len(exact_matches),
                "normalized_matches": len(normalized_matches),
                "zero_padding_issues": len(normalized_matches) - len(exact_matches)
            }
        }

        current_app.logger.info(f"Tiempo comparación: {time.time() - compare_time:.2f}s")
        # Limpieza de archivos temporales
        for path in temp_file_paths + [consolidated_file, csv_path, pdf_path]:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception as e:
                current_app.logger.warning(f"No se pudo eliminar archivo temporal {path}: {str(e)}")

        # Construir respuesta
        total_time = time.time() - start_time
        response_data = {
            "message": "Procesamiento completado exitosamente.",
            "processing_time_seconds": round(total_time, 2),
            "download_links": {
                "csv": f"/download/csv?user_id={user_id}&filename={csv_filename}",
                "pdf": f"/download/pdf?user_id={user_id}&filename={pdf_filename}"
            },
            "uploaded_files": uploaded_files,
            "comparison_results": comparison_results,
            "errors": errors
        }

        return jsonify(response_data), 200

    except Exception as e:
        current_app.logger.error(f"Error en process-all: {str(e)}", exc_info=True)
        return jsonify({
            "error": "Error interno del servidor",
            "details": str(e)
        }), 500
        
@main.route('/api/files', methods=['GET'])
def list_files():
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({"error": "El parámetro user_id es requerido"}), 400

        filterType = request.args.get('tipo', '').lower()
        typeFile = ['pdf', 'csv', 'xlsx']
        if filterType in typeFile:
            searchType = [filterType]
        else:
            searchType = typeFile

        # Obtener parámetros de paginación
        try:
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 10))
            if page < 1 or limit < 1:
                raise ValueError
        except ValueError:
            return jsonify({"error": "Los parámetros page y limit deben ser enteros positivos"}), 400

        search_term = request.args.get('search', '').strip().lower()

        bucket_name = 'uploads'
        result_files = []

        for type in searchType:
            folder = f"{type}/{user_id}"
            try:
                response = supabase.storage.from_(bucket_name).list(folder)
                if not response:
                    continue

                for file_info in response:
                    file_name = file_info.get('name', '')
                    if not file_name or file_name.startswith('.'):
                        continue

                    if search_term and search_term not in file_name.lower():
                        continue
                    
                    file_path = f"{folder}/{file_name}"

                    try:
                        url_descarga = supabase.storage.from_(bucket_name).get_public_url(file_path)
                        result_files.append({
                            "nombre": file_name,
                            "tipo": type,
                            "fecha_subida": file_info.get('created_at', datetime.now().isoformat()),
                            "tamano": file_info.get('metadata', {}).get('size', 0),
                            "url": url_descarga
                        })
                    except Exception as e:
                        print(f"Error al obtener URL para {file_path}: {str(e)}")
                        continue

            except Exception as e:
                print(f"Error al listar {type}: {str(e)}")
                continue

        # Ordenar por fecha (recientes primero)
        result_files.sort(key=lambda x: x['fecha_subida'], reverse=True)
        
        totalFiles = len(result_files)
        start = (page - 1) * limit
        end = start + limit
        paginatedFiles = result_files[start:end]

        return jsonify({
            "success": True,
            "archivos": paginatedFiles,
            "paginacion": {
                "total": totalFiles,
                "page": page,
                "limit": limit,
                "pages": (totalFiles + limit - 1) // limit  # Redondeo hacia arriba
            }
        }), 200

    except Exception as e:
        print(f"Error general: {str(e)}")
        return jsonify({
            "error": "Error interno del servidor",
            "details": str(e)
        }), 500

@main.route('/download/<tipo>', methods=['GET'])
def descargar_archivo(tipo):
    try:
        user_id = request.args.get('user_id')
        filename = request.args.get('filename')

        if not all([user_id, filename]):
            return jsonify({
                "error": "Parámetros faltantes",
                "requeridos": ["user_id", "filename"]
            }), 400

        # Validar tipo de archivo
        valid_types = ['pdf', 'csv', 'xlsx']
        if tipo not in valid_types:
            return jsonify({
                "error": "Tipo de archivo no válido",
                "tipos_aceptados": valid_types
            }), 400

        # Validar nombre de archivo para seguridad
        if not secure_filename(filename) == filename:
            return jsonify({"error": "Nombre de archivo no válido"}), 400

        # Construir ruta en Supabase
        file_path = f"{tipo}/{user_id}/{filename}"
        bucket_name = 'uploads'

        try:
            # Descargar el archivo desde Supabase
            file_data = supabase.storage.from_(bucket_name).download(file_path)
            
            if not file_data:
                return jsonify({"error": "Archivo no encontrado"}), 404

            # Crear respuesta
            response = make_response(file_data)
            
            # Configurar headers según tipo de archivo
            if tipo == 'pdf':
                response.headers['Content-Type'] = 'application/pdf'
                response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
            elif tipo == 'csv':
                response.headers['Content-Type'] = 'text/csv'
                response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
            else:  # xlsx
                response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
            
            return response

        except Exception as download_error:
            current_app.logger.error(f"Error al descargar: {str(download_error)}")
            return jsonify({
                "error": "No se pudo descargar el archivo",
                "details": str(download_error)
            }), 500

    except Exception as e:
        current_app.logger.error(f"Error en descarga: {str(e)}")
        return jsonify({
            "error": "Error interno al procesar la solicitud",
            "details": str(e)
        }), 500