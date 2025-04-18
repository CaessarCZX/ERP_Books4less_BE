
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
    Endpoint para subir archivos Excel directamente a Supabase sin procesamiento.
    Los archivos se guardan en la carpeta 'xlsx/{user_id}/'
    """
    try:
        # Verificar que se haya enviado un archivo
        if 'file' not in request.files:
            return jsonify({"error": "No se ha enviado ningún archivo"}), 400
            
        file = request.files['file']
        user_id = request.form.get('user_id')
        
        # Validaciones básicas
        if not user_id:
            return jsonify({"error": "El parámetro user_id es requerido"}), 400
            
        if file.filename == '':
            return jsonify({"error": "Nombre de archivo vacío"}), 400
            
        # Verificar que sea un archivo Excel
        file_extension = os.path.splitext(file.filename)[1].lower()
        if file_extension not in ['.xlsx', '.xls']:
            return jsonify({"error": "Solo se permiten archivos Excel (.xlsx, .xls)"}), 400
        
        # Crear nombre único para el archivo
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        original_filename = secure_filename(file.filename)
        new_filename = f"{os.path.splitext(original_filename)[0]}_{timestamp}{file_extension}"
        
        # Guardar temporalmente el archivo
        temp_dir = os.path.join(UPLOAD_FOLDER, "temp_uploads")
        os.makedirs(temp_dir, exist_ok=True)
        temp_path = os.path.join(temp_dir, new_filename)
        file.save(temp_path)
        
        # Ruta de destino en Supabase
        destination_path = f"xlsx/{user_id}/{new_filename}"
        
        # Subir a Supabase
        upload_response = upload_to_supabase(temp_path, destination_path)
        
        # Eliminar archivo temporal
        try:
            os.remove(temp_path)
        except Exception as e:
            print(f"Error al eliminar archivo temporal: {e}")
        
        if not upload_response:
            return jsonify({"error": "Error al subir el archivo a Supabase"}), 500
            
        # Obtener URL pública del archivo
        try:
            file_url = supabase.storage.from_('uploads').get_public_url(destination_path)
        except Exception as e:
            file_url = "URL no disponible"
            print(f"Error al obtener URL pública: {e}")
        
        return jsonify({
            "message": "Archivo Excel subido exitosamente",
            "filename": new_filename,
            "original_filename": original_filename,
            "file_url": file_url,
            "destination_path": destination_path
        }), 200
        
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
    - Maneja archivos con nombres duplicados usando timestamps únicos
    - Formatea correctamente las fechas (solo día/mes/año)
    - Genera archivos con nombres únicos para evitar conflictos
    - Incluye manejo robusto de errores
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
                # Manejar formato ISO (2023-08-15T14:30:00Z)
                if 'T' in date_str:
                    date_part = date_str.split('T')[0]
                    date_obj = datetime.strptime(date_part, "%Y-%m-%d")
                else:
                    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                return date_obj.strftime("%m/%d/%Y")
            except:
                return date_str  # Si falla, devolver el valor original

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
                .select('item_number,description').eq('user_id', user_id).execute()
            reference_items = pd.DataFrame(reference_response.data if reference_response.data else [])
            reference_set = set(reference_items['item_number'].astype(str).str.strip()) if not reference_items.empty else set()
        except Exception as e:
            current_app.logger.error(f"Error al obtener referencia: {str(e)}")
            reference_items = pd.DataFrame()
            reference_set = set()
        
        current_app.logger.info(f"Tiempo carga referencia: {time.time() - reference_time:.2f}s")

        # 2. Procesar archivos subidos con nombres únicos
        upload_time = time.time()
        temp_file_paths = []
        errors = []
        uploaded_files = []

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

                # Subir a Supabase con manejo de duplicados
                supa_path = f"xlsx/{user_id}/{new_filename}"
                try:
                    upload_to_supabase(temp_path, supa_path)
                    uploaded_files.append({
                        'original_name': original_filename,
                        'stored_name': new_filename
                    })
                except Exception as upload_error:
                    if 'Duplicate' in str(upload_error):
                        current_app.logger.warning(f"Archivo duplicado, omitiendo: {supa_path}")
                        continue
                    raise
                
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

        # 4. Generar CSV con nombre único
        csv_time = time.time()
        excel_base = secure_filename(files[0].filename.rsplit('.', 1)[0])
        csv_filename = f"{excel_base}_{timestamp}.csv"
        csv_path = os.path.join(DOWNLOAD_FOLDER, csv_filename)
        
        try:
            csv_result = create_csv(consolidated_file, csv_path)
            if "error" in csv_result:
                return jsonify(csv_result), 500
            
            # Subir a Supabase
            upload_to_supabase(csv_path, f"csv/{user_id}/{csv_filename}")
        except Exception as e:
            current_app.logger.error(f"Error al generar CSV: {str(e)}")
            return jsonify({"error": "Error al generar CSV", "details": str(e)}), 500
        
        current_app.logger.info(f"Tiempo generación CSV: {time.time() - csv_time:.2f}s")

        # 5. Generar PDF con nombre único
        pdf_time = time.time()
        pdf_filename = f"{excel_base}_{timestamp}.pdf"
        pdf_path = os.path.join(DOWNLOAD_FOLDER, pdf_filename)
        
        try:
            pdf_result = create_pdf(consolidated_file, pdf_path, discount_rate, form_data)
            if "error" in pdf_result:
                return jsonify(pdf_result), 500
            
            # Subir a Supabase
            upload_to_supabase(pdf_path, f"pdf/{user_id}/{pdf_filename}")
        except Exception as e:
            current_app.logger.error(f"Error al generar PDF: {str(e)}")
            return jsonify({"error": "Error al generar PDF", "details": str(e)}), 500
        
        current_app.logger.info(f"Tiempo generación PDF: {time.time() - pdf_time:.2f}s")

        # 6. Comparación con datos de referencia
        compare_time = time.time()
        comparison_results = {
            "total_reference_items": len(reference_set),
            "matched_items_count": 0,
            "unmatched_items": [],
            "total_processed_items": 0,
            "match_percentage": 0
        }

        try:
            consolidated_df = pd.read_excel(consolidated_file, usecols=['item_id'])
            processed_items = set(consolidated_df['item_id'].astype(str).str.strip())
            comparison_results['total_processed_items'] = len(processed_items)

            missing_items = reference_set - processed_items
            
            if missing_items:
                missing_data = reference_items[reference_items['item_number'].isin(missing_items)]
                comparison_results['unmatched_items'] = missing_data.to_dict('records')
            
            comparison_results['matched_items_count'] = len(reference_set) - len(missing_items)
            comparison_results['match_percentage'] = round(
                (comparison_results['matched_items_count'] / len(reference_set)) * 100, 2
            ) if reference_set else 0

        except Exception as e:
            current_app.logger.error(f"Error en comparación: {str(e)}")
            comparison_results['comparison_error'] = str(e)

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