
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
            "email": email
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
        # Validación básica
        if 'user_id' not in request.form or 'file' not in request.files:
            return jsonify({"error": "user_id y file son requeridos"}), 400

        user_id = request.form['user_id']
        file = request.files['file']

        if file.filename == '':
            return jsonify({"error": "Nombre de archivo no válido"}), 400

        # Procesamiento del archivo
        ext = file.filename.split('.')[-1].lower()
        if ext not in ['csv', 'xlsx']:
            return jsonify({"error": "Formato no soportado"}), 400

        # Leer archivo directamente a DataFrame sin guardar temporalmente
        try:
            if ext == 'xlsx':
                df = pd.read_excel(file)
            else:
                # Leer una muestra para detectar el delimitador
                sample = file.stream.read(1024).decode('utf-8')
                file.stream.seek(0)
                delimiter = ',' if ',' in sample else ';'
                df = pd.read_csv(file, delimiter=delimiter)
        except Exception as e:
            return jsonify({"error": f"Error al leer archivo: {str(e)}"}), 400

        # Validar columnas
        if not all(col in df.columns for col in ['No.', 'Description']):
            return jsonify({"error": "El archivo debe contener columnas 'No.' y 'Description'"}), 400

        # Limpieza y preparación de datos
        df = df[['No.', 'Description']].dropna()
        df['No.'] = df['No.'].astype(str).str.strip()
        df['Description'] = df['Description'].astype(str).str.strip()

        # Convertir a formato JSON para Supabase
        records = df.rename(columns={'No.': 'item_number'}).to_dict('records')
        
        # Optimización 1: Usar COPY en lugar de INSERT para grandes volúmenes
        if len(records) > 1000:
            # Crear archivo temporal CSV
            temp_csv = os.path.join(UPLOAD_FOLDER, f"temp_ref_{uuid.uuid4().hex}.csv")
            df.rename(columns={'No.': 'item_number'}).to_csv(temp_csv, index=False)
            
            try:
                # Subir CSV a Supabase Storage
                upload_path = f"temp_refs/{user_id}/{os.path.basename(temp_csv)}"
                with open(temp_csv, 'rb') as f:
                    supabase.storage.from_('uploads').upload(upload_path, f)
                
                # Ejecutar COPY desde CSV
                copy_response = supabase.rpc('copy_from_storage', {
                    'table_name': 'item_reference',
                    'file_path': upload_path,
                    'format': 'csv',
                    'options': {
                        'header': True,
                        'delimiter': ',',
                        'user_id': user_id,
                        'source_file': secure_filename(file.filename)
                    }
                }).execute()
                
                os.remove(temp_csv)
                supabase.storage.from_('uploads').remove([upload_path])
                
                return jsonify({
                    "message": f"{len(records)} items subidos mediante COPY",
                    "total_items": len(records)
                }), 200
                
            except Exception as e:
                if os.path.exists(temp_csv):
                    os.remove(temp_csv)
                current_app.logger.error(f"Error en COPY: {str(e)}")
                # Continuar con inserción normal si falla COPY

        # Optimización 2: Inserción masiva en una sola operación
        records_to_insert = [{
            'item_number': record['item_number'],
            'description': record['Description'],
            'user_id': user_id,
            'source_file': secure_filename(file.filename)
        } for record in records]

        try:
            # Usar inserción masiva con upsert para evitar duplicados
            response = supabase.table('item_reference').upsert(
                records_to_insert,
                on_conflict='item_number,user_id'
            ).execute()
            
            inserted_count = len(response.data) if response.data else 0
            
            return jsonify({
                "message": f"{inserted_count} items subidos/actualizados",
                "total_items": inserted_count
            }), 200
            
        except Exception as e:
            current_app.logger.error(f"Error en inserción masiva: {str(e)}")
            
            # Optimización 3: Si falla la inserción masiva, intentar por lotes más pequeños
            batch_size = 500
            total_inserted = 0
            errors = []

            for i in range(0, len(records_to_insert), batch_size):
                batch = records_to_insert[i:i + batch_size]
                try:
                    batch_response = supabase.table('item_reference').insert(batch).execute()
                    if batch_response.data:
                        total_inserted += len(batch_response.data)
                except Exception as batch_error:
                    errors.append(f"Lote {i//batch_size}: {str(batch_error)}")

            if errors:
                current_app.logger.error(f"Errores en lotes: {errors}")
                return jsonify({
                    "message": f"Subida parcial: {total_inserted} items",
                    "total_items": total_inserted,
                    "errors": errors
                }), 207

            return jsonify({
                "message": f"{total_inserted} items subidos por lotes",
                "total_items": total_inserted
            }), 200

    except Exception as e:
        current_app.logger.error(f"Error inesperado: {str(e)}", exc_info=True)
        return jsonify({
            "error": "Error interno del servidor",
            "details": str(e)
        }), 500

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
    Ruta optimizada con validación de duplicados que:
    - Verifica archivos duplicados antes de procesar
    - Procesa múltiples archivos eficientemente
    - Realiza comparación rápida con datos de referencia
    - Genera reportes en CSV y PDF
    - Retorna resultados detallados de coincidencias
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

        # Datos del formulario
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

        # Procesamiento de archivos
        files = request.files.getlist('files')
        if not files:
            return jsonify({"error": "No se han enviado archivos."}), 400

        # Verificar duplicados antes de procesar
        filenames = [file.filename.strip() for file in files if file]
        duplicates = {x for x in filenames if filenames.count(x) > 1}
        
        if duplicates:
            return jsonify({
                "error": "Archivos duplicados detectados",
                "duplicates": list(duplicates),
                "message": "Por favor cambie los nombres de los archivos duplicados y vuelva a intentar."
            }), 400

        # 1. Obtener datos de referencia de forma optimizada
        reference_time = time.time()
        reference_response = supabase.table('item_reference')\
            .select('item_number,description').eq('user_id', user_id).execute()
        
        # Convertir a DataFrame y luego a conjunto para búsquedas rápidas
        reference_items = pd.DataFrame(reference_response.data if reference_response.data else [])
        reference_set = set(reference_items['item_number'].astype(str).str.strip()) if not reference_items.empty else set()
        current_app.logger.info(f"Tiempo carga referencia: {time.time() - reference_time:.2f}s")

        # 2. Procesar archivos subidos
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
                # Guardar archivo temporal
                new_filename = f"{secure_filename(original_filename.rsplit('.', 1)[0])}.{ext}"
                temp_path = os.path.join(UPLOAD_FOLDER, new_filename)
                file.save(temp_path)
                temp_file_paths.append(temp_path)

                # Subir a Supabase (en segundo plano)
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

        # 3. Consolidar archivos con manejo de memoria
        consolidate_time = time.time()
        consolidated_file, consolidate_error = consolidate_files(temp_file_paths)
        if consolidate_error:
            return jsonify({"error": consolidate_error}), 500
        current_app.logger.info(f"Tiempo consolidación: {time.time() - consolidate_time:.2f}s")

        # 4. Generar CSV optimizado
        csv_time = time.time()
        excel_base = secure_filename(files[0].filename.rsplit('.', 1)[0])
        csv_filename = f"{excel_base}.csv"
        csv_path = os.path.join(DOWNLOAD_FOLDER, csv_filename)
        csv_result = create_csv(consolidated_file, csv_path)
        
        if "error" in csv_result:
            return jsonify(csv_result), 500
        current_app.logger.info(f"Tiempo generación CSV: {time.time() - csv_time:.2f}s")

        # 5. Generar PDF
        pdf_time = time.time()
        pdf_filename = f"{excel_base}.pdf"
        pdf_path = os.path.join(DOWNLOAD_FOLDER, pdf_filename)
        pdf_result = create_pdf(consolidated_file, pdf_path, discount_rate, form_data)
        
        if "error" in pdf_result:
            return jsonify(pdf_result), 500
        current_app.logger.info(f"Tiempo generación PDF: {time.time() - pdf_time:.2f}s")

        # 6. Subir archivos generados (en segundo plano)
        upload_to_supabase(csv_path, f"csv/{user_id}/{csv_filename}")
        upload_to_supabase(pdf_path, f"pdf/{user_id}/{pdf_filename}")

        # 7. Comparación optimizada con datos de referencia
        compare_time = time.time()
        comparison_results = {
            "total_reference_items": len(reference_set),
            "matched_items_count": 0,
            "unmatched_items": [],
            "total_processed_items": 0,
            "match_percentage": 0
        }

        try:
            # Leer solo la columna necesaria para comparación
            consolidated_df = pd.read_excel(consolidated_file, usecols=['item_id'])
            processed_items = set(consolidated_df['item_id'].astype(str).str.strip())
            comparison_results['total_processed_items'] = len(processed_items)

            # Encontrar diferencias de forma optimizada
            missing_items = reference_set - processed_items
            
            # Solo obtener descripciones para items no encontrados (optimización)
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
        for path in temp_file_paths:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except:
                pass

        if os.path.exists(consolidated_file):
            try:
                os.remove(consolidated_file)
            except:
                pass

        # Construir respuesta final
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